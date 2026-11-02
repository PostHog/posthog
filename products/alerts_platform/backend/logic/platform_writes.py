"""Writes to a configuration through the API, for the configurations the platform owns.

A configuration its source owns is a copy of the source's own row, which the source's API writes
and the next check reads back. Writing the copy here would fork it, so those are refused.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone as django_timezone

from pydantic import ValidationError as PydanticValidationError

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
from posthog.models.signals import model_activity_signal

from products.alerts_platform.backend.facade.contracts import (
    MAX_EVALUATION_PERIODS,
    MAX_STORED_INTEGER,
    Grouping,
    GroupingMode,
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    PlatformAlertNotEditable,
    PlatformAlertSnapshot,
    SourceCreate,
    SourceKind,
    UnknownPlatformAlertGroup,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.facade.scheduling import validate_and_normalize_schedule_restriction
from products.alerts_platform.backend.logic import (
    control_plane,
    platform_lifecycle,
    platform_reads,
    rule_metadata,
    source_configs,
)
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration


class MissingPlatformCopy(Exception):
    """A source row marked platform-owned with no platform copy behind it."""


def edit_of(configuration: PlatformAlertConfiguration) -> PlatformAlertConfigurationEdit:
    return PlatformAlertConfigurationEdit(
        name=configuration.name,
        enabled=configuration.enabled,
        source_config=configuration.source_config,
        grouping=Grouping.from_stored(configuration.grouping),
        schedule_restriction=configuration.schedule_restriction,
        evaluation_periods=configuration.evaluation_periods,
        datapoints_to_alarm=configuration.datapoints_to_alarm,
        cooldown_minutes=configuration.cooldown_minutes,
        labels=configuration.labels,
        annotations=configuration.annotations,
    )


def _validated(
    source_kind: SourceKind,
    current: PlatformAlertConfigurationEdit | None,
    edit: PlatformAlertConfigurationEdit,
    *,
    team_id: int,
) -> PlatformAlertConfigurationEdit:
    spec = source_configs.spec(source_kind)
    if spec is None:
        raise PlatformAlertNotEditable(f"{source_kind} alerts cannot be edited through this API.")
    for name, value in (
        ("evaluation_periods", edit.evaluation_periods),
        ("datapoints_to_alarm", edit.datapoints_to_alarm),
    ):
        if not 1 <= value <= MAX_EVALUATION_PERIODS:
            raise InvalidPlatformAlertEdit(name, f"Must be between 1 and {MAX_EVALUATION_PERIODS}.")
    if edit.datapoints_to_alarm > edit.evaluation_periods:
        raise InvalidPlatformAlertEdit("datapoints_to_alarm", "Cannot exceed evaluation_periods.")
    if not 0 <= edit.cooldown_minutes <= MAX_STORED_INTEGER:
        raise InvalidPlatformAlertEdit("cooldown_minutes", f"Must be between 0 and {MAX_STORED_INTEGER}.")
    try:
        schedule_restriction = validate_and_normalize_schedule_restriction(edit.schedule_restriction)
    except ValueError as error:
        raise InvalidPlatformAlertEdit("schedule_restriction", str(error)) from error
    try:
        rule_metadata.validate_labels(edit.labels)
    except rule_metadata.InvalidRuleMetadata as error:
        raise InvalidPlatformAlertEdit("labels", str(error)) from error
    try:
        rule_metadata.validate_annotations(edit.annotations, {*edit.grouping.keys, *edit.labels})
    except rule_metadata.InvalidRuleMetadata as error:
        raise InvalidPlatformAlertEdit("annotations", str(error)) from error
    source_config = edit.source_config
    # Settings the edit leaves alone may predate the schema, or name rows deleted since, and must not
    # block an unrelated change.
    sets_source_config = current is None or source_config != current.source_config
    if sets_source_config:
        try:
            parsed = spec.model.model_validate(source_config)
        except PydanticValidationError as error:
            first = error.errors()[0]
            location = ".".join(str(part) for part in first["loc"])
            raise InvalidPlatformAlertEdit("source_config", f"Invalid at `{location}`: {first['msg']}") from error
        source_config = parsed.model_dump(mode="json", exclude_unset=True)
    validated = replace(edit, source_config=source_config, schedule_restriction=schedule_restriction)
    spec.validate(validated)
    if sets_source_config and spec.check_in_team is not None:
        spec.check_in_team(team_id=team_id, edit=validated)
    return validated


def update_configuration(
    *,
    team_id: int,
    source_kinds: Sequence[str],
    configuration_id: UUID,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
) -> PlatformAlertConfigurationView | None:
    """Applies `change` to the configuration's current settings under its row lock, and mirrors the
    result onto the source's own row.

    None when the configuration does not exist or its kind is not among `source_kinds`. Taking a
    function rather than the new settings lets a partial update merge with what is stored inside
    the lock, so two partial updates of different fields both survive.
    """
    readable = PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(
        id=configuration_id, source_kind__in=list(source_kinds)
    )
    with transaction.atomic():
        found = readable.values_list("source_kind", "legacy_configuration_id").first()
        if found is None:
            return None
        source_kind, legacy_configuration_id = found
        spec = source_configs.spec(SourceKind(source_kind))
        mirror = spec.mirror if spec is not None else None
        write_source = (
            mirror(team_id=team_id, legacy_configuration_id=legacy_configuration_id)
            if mirror is not None and legacy_configuration_id is not None
            else None
        )
        configuration = readable.select_for_update().first()
        if configuration is None:
            return None
        edit, pending = _apply(configuration, change, now=django_timezone.now())
        if write_source is not None:
            write_source(edit)
        control_plane.announce_after_commit(pending)

    return platform_reads.get_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id
    )


def create_configuration(
    *, team_id: int, source_kind: SourceKind, edit: PlatformAlertConfigurationEdit, created_by_id: int | None
) -> PlatformAlertConfigurationView:
    """Creates an alert the platform owns: itself for a native kind, and otherwise through the hook
    its source registered.

    Raises `PlatformAlertNotEditable` for a kind the API cannot create, `InvalidPlatformAlertEdit` for
    settings its source kind rejects, and `PlatformAlertCreateRefused` when the source refuses.
    """
    spec = source_configs.spec(source_kind)
    if spec is None or not spec.creatable:
        raise PlatformAlertNotEditable(f"{source_kind} alerts cannot be created through this API.")
    validated = _validated(source_kind, None, edit, team_id=team_id)
    if spec.native is not None:
        configuration = platform_lifecycle.create_native_configuration(
            team_id=team_id,
            source_kind=source_kind,
            edit=validated,
            check_interval_minutes=spec.native.check_interval_minutes,
            destinations_owner=PlatformAlertOwner.PLATFORM
            if spec.native.platform_destinations
            else PlatformAlertOwner.SOURCE,
            now=django_timezone.now(),
        )
    else:
        assert spec.create is not None
        configuration = _create_through_source(team_id, source_kind, spec.create, validated, created_by_id)

    view = platform_reads.get_configuration(
        team_id=team_id, source_kinds=[source_kind.value], configuration_id=configuration.id
    )
    assert view is not None
    return view


def _create_through_source(
    team_id: int,
    source_kind: SourceKind,
    create: SourceCreate,
    validated: PlatformAlertConfigurationEdit,
    created_by_id: int | None,
) -> PlatformAlertConfiguration:
    with transaction.atomic():
        legacy_configuration_id = create(team_id=team_id, edit=validated, created_by_id=created_by_id)
        configuration = _locked_owned_copy(team_id, legacy_configuration_id)
        if configuration is None:
            raise MissingPlatformCopy(f"The {source_kind} source created no platform copy of {legacy_configuration_id}")
        # The copy was written as the source's and then handed over, so no write logged its creation.
        model_activity_signal.send(
            sender=PlatformAlertConfiguration,
            scope=PlatformAlertConfiguration.__name__,
            before_update=None,
            after_update=configuration,
            activity="created",
            user=get_current_user(),
            was_impersonated=get_was_impersonated(),
        )
        # The source wrote the settings it shares with the copy. This writes the rest, such as grouping.
        _, pending = _apply(configuration, lambda _: validated, now=django_timezone.now())
        control_plane.announce_after_commit(pending)
    return configuration


# A snoozed group keeps its slot under `max_instances`, so a forgotten long snooze would hold it.
MAX_GROUP_SNOOZE: Final = timedelta(days=30)


def snooze_group(
    *,
    team_id: int,
    source_kinds: Sequence[str],
    configuration_id: UUID,
    grouping_key: str,
    snooze_until: datetime | None,
) -> PlatformAlertSnapshot | None:
    """Sets or clears the mute of one group of a configuration the platform owns.

    None when the configuration does not exist or its kind is not among `source_kinds`.

    Unlike a snooze of the whole alert, this leaves the group's firing open and the schedule alone.
    The alert's other groups still need their checks, so this group's checks go on too. Ending the
    firing would send a resolve now, and a breach that goes on would trigger a new incident at the
    next check. The mute holds the group's messages, and its incident edges still go out.
    """
    now = django_timezone.now()
    if snooze_until is not None and snooze_until <= now:
        raise InvalidPlatformAlertEdit("snooze_until", "Pick a time in the future, or send null to unsnooze.")
    if snooze_until is not None and snooze_until > now + MAX_GROUP_SNOOZE:
        raise InvalidPlatformAlertEdit(
            "snooze_until", f"A group can be snoozed for up to {MAX_GROUP_SNOOZE.days} days. Pick an earlier time."
        )
    with transaction.atomic():
        # The configuration before its instance, the order `record_outcomes` locks them in.
        configuration = (
            PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
            .select_for_update()
            .filter(id=configuration_id, source_kind__in=list(source_kinds))
            .first()
        )
        if configuration is None:
            return None
        if configuration.owner != PlatformAlertOwner.PLATFORM:
            raise PlatformAlertNotEditable(
                f"This alert is managed by the {configuration.source_kind} product, so its groups cannot be "
                "snoozed here. Snooze the whole alert there instead."
            )
        # The one instance of an ungrouped alert is the whole alert, whose snooze also ends the firing.
        if Grouping.from_stored(configuration.grouping).mode == GroupingMode.SINGLE:
            raise InvalidPlatformAlertEdit(
                "grouping_key", "This alert is not grouped, so it has no group to snooze. Snooze the whole alert."
            )
        alert = (
            PlatformAlert.objects.for_team(team_id, canonical=True)
            .filter(configuration=configuration, grouping_key=grouping_key)
            .first()
        )
        if alert is None:
            raise UnknownPlatformAlertGroup(grouping_key)
        alert.snooze_until = snooze_until
        alert.save(update_fields=["snooze_until"])
    return platform_reads.instance_view(alert, configuration)


def update_owned_copy(
    *,
    team_id: int,
    legacy_configuration_id: UUID,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
    snooze_until: datetime | None,
    snooze_changed: bool,
) -> None:
    """Applies an edit the source made to its own row onto the platform's copy. Nothing is mirrored
    back, because the source already wrote its row. A snooze the edit set or cleared becomes the
    copy's mute."""
    with transaction.atomic():
        configuration = _locked_owned_copy(team_id, legacy_configuration_id)
        if configuration is None:
            return
        now = django_timezone.now()
        # A snooze ends the firing, as on the logs stack. A firing after it opens a new incident.
        snoozing = snooze_changed and snooze_until is not None and snooze_until > now
        _, pending = _apply(configuration, change, now=now, snoozing=snoozing)
        if snooze_changed:
            platform_lifecycle.write_snooze(configuration, snooze_until, now=now)
        control_plane.announce_after_commit(pending)


def close_owned_firings_now(*, team_id: int, legacy_configuration_id: UUID) -> None:
    """Ends the firings of a copy the platform owns and sends their resolves before returning.

    For a delete, which removes the destinations a delivery after commit would look up. Call it
    outside the delete's transaction, so the history it reads and the state it moved have committed.
    """
    _close_firings_now(lambda: _locked_owned_copy(team_id, legacy_configuration_id))


def _close_firings_now(locked: Callable[[], PlatformAlertConfiguration | None]) -> None:
    with transaction.atomic():
        configuration = locked()
        pending = (
            None
            if configuration is None
            else control_plane.end_firings(configuration, reason="deleted", now=django_timezone.now())
        )
    control_plane.announce_now(pending)


def delete_configuration(*, team_id: int, source_kinds: Sequence[str], configuration_id: UUID) -> bool:
    """Deletes a configuration the platform owns, itself for a native kind and otherwise through the
    hook its source registered. False when the configuration does not exist or its kind is not among
    `source_kinds`.

    Raises `PlatformAlertNotEditable` for a configuration its source owns, or of a kind the API
    cannot delete. Runs outside any transaction, because the resolves go out first.
    """
    found = (
        PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
        .filter(id=configuration_id, source_kind__in=list(source_kinds))
        .values_list("source_kind", "legacy_configuration_id", "owner")
        .first()
    )
    if found is None:
        return False
    source_kind, legacy_configuration_id, owner = found
    if owner != PlatformAlertOwner.PLATFORM:
        raise PlatformAlertNotEditable(f"This alert is managed by the {source_kind} product. Delete it there.")
    spec = source_configs.spec(SourceKind(source_kind))
    if spec is not None and spec.native is not None:
        _delete_native(team_id, configuration_id, spec.native)
    elif spec is not None and spec.delete is not None and legacy_configuration_id is not None:
        spec.delete(team_id=team_id, legacy_configuration_id=legacy_configuration_id)
    else:
        raise PlatformAlertNotEditable(f"{source_kind} alerts cannot be deleted through this API.")
    return True


def _delete_native(team_id: int, configuration_id: UUID, native: NativeAlertLifecycle) -> None:
    configurations = PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(id=configuration_id)
    # Before the destinations go, so an incident manager still gets the resolve for an open firing.
    _close_firings_now(lambda: configurations.select_for_update().first())
    # In the delete's transaction, so a delete that fails keeps the alert's destinations. An
    # `AlertDestination` row goes with its configuration, so there is nothing to remove first.
    remove = native.remove_destinations
    _delete_each(
        configurations,
        before_delete=None if remove is None else lambda: remove(team_id=team_id, configuration_id=configuration_id),
    )


def delete_owned_copy(*, team_id: int, legacy_configuration_id: UUID) -> None:
    """Deletes the copy of a source alert the platform owns, with its instances and threads."""
    _delete_each(
        PlatformAlertConfiguration.objects.for_team(team_id).filter(
            legacy_configuration_id=legacy_configuration_id, owner=PlatformAlertOwner.PLATFORM
        )
    )


def _delete_each(
    configurations: QuerySet[PlatformAlertConfiguration], *, before_delete: Callable[[], None] | None = None
) -> None:
    with transaction.atomic():
        # The configuration before its children, the order `record_outcomes` locks them in. The
        # cascade deletes the children first, so without this the two can deadlock. Each row goes
        # through the model's own delete, because a queryset delete skips the activity log.
        locked = list(configurations.select_for_update())
        if before_delete is not None:
            before_delete()
        for configuration in locked:
            configuration.delete()


def _locked_owned_copy(team_id: int, legacy_configuration_id: UUID) -> PlatformAlertConfiguration | None:
    configuration = (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .select_for_update()
        .filter(legacy_configuration_id=legacy_configuration_id, owner=PlatformAlertOwner.PLATFORM)
        .first()
    )
    if configuration is None:
        # A source row marked platform-owned without a copy is a broken handover. The source's own
        # edit still saves, so the user is not blocked, and the report makes the gap visible.
        capture_exception(
            MissingPlatformCopy(f"No platform copy owns source alert {legacy_configuration_id}"),
            {"team_id": team_id, "legacy_configuration_id": str(legacy_configuration_id)},
        )
    return configuration


def _apply(
    configuration: PlatformAlertConfiguration,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
    *,
    now: datetime,
    snoozing: bool = False,
) -> tuple[PlatformAlertConfigurationEdit, control_plane.PendingClose | None]:
    """Validates and writes an edit onto a configuration locked by the caller, and ends the firings it
    makes meaningless."""
    if configuration.owner != PlatformAlertOwner.PLATFORM:
        raise PlatformAlertNotEditable(
            f"This alert is managed by the {configuration.source_kind} product. Edit it there."
        )
    current = edit_of(configuration)
    edit = _validated(SourceKind(configuration.source_kind), current, change(current), team_id=configuration.team_id)

    regrouped = not edit.grouping.splits_like(current.grouping)
    ending = control_plane.ending_reason(current, edit, regrouped=regrouped, snoozing=snoozing)
    # Before the instances change, so the history rows name the firings as they ran.
    pending = control_plane.end_firings(configuration, reason=ending, now=now) if ending else None

    platform_lifecycle.write_edit(configuration, edit, regrouped=regrouped, now=now)
    return edit, pending
