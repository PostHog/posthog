"""Writes to a configuration through the API, for the configurations the platform owns.

A configuration its source owns is a copy of the source's own row, which the source's API writes
and the next check reads back. Writing the copy here would fork it, so those are refused.
"""

from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Case, QuerySet, Value, When
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
    NativeEditGuard,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    PlatformAlertCreateRefused,
    PlatformAlertNotEditable,
    PlatformAlertSnapshot,
    PlatformAlertUpsert,
    SourceCreate,
    SourceKind,
    UnknownPlatformAlertGroup,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
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


def hold_cap_lock(team_id: int, source_kind: SourceKind) -> None:
    """Serializes a team's cap checks for a kind until the caller's transaction ends. A source that
    also creates alerts outside the platform takes it too, so two creates cannot both pass a count."""
    # In autocommit the lock ends with its own statement, so it would serialize nothing.
    if not connection.in_atomic_block:
        raise RuntimeError("The cap lock must be taken inside a transaction.")
    # A transaction-scoped advisory lock per team and kind, rather than a lock on the Team row, which
    # foreign-key checks from every child write also take.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"alerts_platform:{team_id}:{source_kind.value}"]
        )


def _admit(
    *,
    team_id: int,
    source_kind: SourceKind,
    current: PlatformAlertConfigurationEdit | None,
    edit: PlatformAlertConfigurationEdit,
    check_interval_minutes: int | None,
) -> None:
    """Runs the source's admission for a write, in the caller's transaction."""
    spec = source_configs.spec(source_kind)
    if spec is None:
        return
    cap = spec.native.max_per_team if spec.native is not None and current is None else None
    if spec.admit is None and cap is None:
        return
    hold_cap_lock(team_id, source_kind)
    if cap is not None and platform_reads.count_configurations(team_id=team_id, source_kind=source_kind.value) >= cap:
        raise PlatformAlertCreateRefused(
            f"This project has reached the limit of {cap} alerts of this type. Delete one to add another."
        )
    if spec.admit is not None:
        spec.admit(team_id=team_id, current=current, edit=edit, check_interval_minutes=check_interval_minutes)


def update_configuration(
    *,
    team_id: int,
    source_kinds: Sequence[str],
    configuration_id: UUID,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
    snooze_until: datetime | None = None,
    snooze_changed: bool = False,
    cadence: PlatformAlertUpsert | None = None,
    rescheduled: bool = False,
    source_checked: bool = False,
) -> PlatformAlertConfigurationView | None:
    """Applies `change` to the configuration's current settings under its row lock, and mirrors the
    result onto the source's own row. With `snooze_changed`, `snooze_until` becomes the whole alert's mute.

    For an alert with no source row, `cadence` writes its schedule as `update_owned_copy` writes a
    copy's, and its kind's `native_edit_guard` refuses what the source's API alone may change. A
    source whose own API checked the edit sets `source_checked` to skip the guard.

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
        if snooze_changed and legacy_configuration_id is not None:
            # The source row keeps the snooze too, and no mirror carries one, so the two would disagree.
            raise InvalidPlatformAlertEdit("snooze_until", f"Snooze this alert in the {source_kind} product.")
        if cadence is not None and legacy_configuration_id is not None:
            # The source row keeps the schedule, and `update_owned_copy` writes it onto the copy.
            raise InvalidPlatformAlertEdit(
                "check_interval_minutes", f"Schedule this alert in the {source_kind} product."
            )
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
        now = django_timezone.now()
        current, previous_state = edit_of(configuration), platform_lifecycle.shown_state(configuration, now=now)
        # A snooze ends the firing, as `update_owned_copy` does for a copy.
        snoozing = snooze_changed and snooze_until is not None and snooze_until > now
        guard = (
            spec.native_edit_guard
            if spec is not None and legacy_configuration_id is None and not source_checked
            else None
        )
        edit, pending = _apply(
            configuration,
            change,
            now=now,
            snoozing=snoozing,
            admit=True,
            guard=guard,
            check_interval_minutes=cadence.check_interval_minutes if cadence is not None else None,
        )
        # After the edit, whose enable would reset the due time the cadence sets, and before the snooze,
        # whose deferred due time the cadence would otherwise overwrite.
        if cadence is not None:
            try:
                platform_lifecycle.write_owned_cadence(configuration, cadence, rescheduled=rescheduled)
            except ValueError as error:
                raise InvalidPlatformAlertEdit("check_interval_minutes", str(error)) from error
        if snooze_changed:
            platform_lifecycle.write_snooze(configuration, snooze_until, now=now)
        if write_source is not None:
            write_source(edit)
        control_plane.announce_after_commit(pending)
        _record_change(
            configuration,
            current,
            edit,
            previous_state=previous_state,
            snooze_changed=snooze_changed,
            snooze_until=snooze_until,
            now=now,
        )

    return platform_reads.get_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id
    )


def create_configuration(
    *,
    team_id: int,
    source_kind: SourceKind,
    edit: PlatformAlertConfigurationEdit,
    created_by_id: int | None,
    natively: bool | None = None,
) -> PlatformAlertConfigurationView:
    """Creates an alert the platform owns: itself for a native kind, and otherwise through the hook
    its source registered. A source that already decided sets `natively`, so the spec does not decide again.

    Raises `PlatformAlertNotEditable` for a kind the API cannot create, `InvalidPlatformAlertEdit` for
    settings its source kind rejects, and `PlatformAlertCreateRefused` when the source refuses.
    """
    spec = source_configs.spec(source_kind)
    if spec is None or not spec.creatable:
        raise PlatformAlertNotEditable(f"{source_kind} alerts cannot be created through this API.")
    validated = _validated(source_kind, None, edit, team_id=team_id)
    if spec.native is not None and (spec.creates_natively(team_id) if natively is None else natively):
        check_interval_minutes = _native_check_interval(spec.native, validated)
        recurrence_unit = (spec.native.check_intervals or {}).get(check_interval_minutes)
        with transaction.atomic():
            _admit(
                team_id=team_id,
                source_kind=source_kind,
                current=None,
                edit=validated,
                check_interval_minutes=check_interval_minutes,
            )
            configuration = platform_lifecycle.create_native_configuration(
                team_id=team_id,
                source_kind=source_kind,
                edit=validated,
                check_interval_minutes=check_interval_minutes,
                recurrence_unit=recurrence_unit,
                destinations_owner=PlatformAlertOwner.PLATFORM
                if spec.native.platform_destinations
                else PlatformAlertOwner.SOURCE,
                created_by_id=created_by_id,
                now=django_timezone.now(),
            )
    else:
        if spec.create is None:
            # A native kind whose creates are switched off.
            raise PlatformAlertNotEditable(f"{source_kind} alerts cannot be created through this API.")
        if validated.check_interval_minutes is not None:
            raise InvalidPlatformAlertEdit("check_interval_minutes", f"A {source_kind} alert sets its own cadence.")
        configuration = _create_through_source(team_id, source_kind, spec.create, validated, created_by_id)

    view = platform_reads.get_configuration(
        team_id=team_id, source_kinds=[source_kind.value], configuration_id=configuration.id
    )
    assert view is not None
    return view


def _native_check_interval(native: NativeAlertLifecycle, edit: PlatformAlertConfigurationEdit) -> int:
    requested = edit.check_interval_minutes
    if requested is None:
        return native.check_interval_minutes
    if native.check_intervals is None:
        raise InvalidPlatformAlertEdit("check_interval_minutes", "Alerts of this type have one fixed cadence.")
    if requested not in native.check_intervals:
        allowed = ", ".join(str(minutes) for minutes in sorted(native.check_intervals))
        raise InvalidPlatformAlertEdit("check_interval_minutes", f"Must be one of: {allowed}.")
    return requested


def _create_through_source(
    team_id: int,
    source_kind: SourceKind,
    create: SourceCreate,
    validated: PlatformAlertConfigurationEdit,
    created_by_id: int | None,
) -> PlatformAlertConfiguration:
    with transaction.atomic():
        _admit(team_id=team_id, source_kind=source_kind, current=None, edit=validated, check_interval_minutes=None)
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
    cadence: PlatformAlertUpsert | None = None,
    rescheduled: bool = False,
    at: datetime | None = None,
    first_enabled_at: datetime | None = None,
) -> None:
    """Applies an edit the source made to its own row onto the platform's copy. Nothing is mirrored
    back, because the source already wrote its row. A snooze the edit set or cleared becomes the
    copy's mute. A changed `cadence`, or `rescheduled`, makes the copy due when the source is.
    `first_enabled_at` is when the source row was first turned on, which the copy takes."""
    with transaction.atomic():
        configuration = _locked_owned_copy(team_id, legacy_configuration_id)
        if configuration is None:
            return
        now = django_timezone.now()
        current, previous_state = edit_of(configuration), platform_lifecycle.shown_state(configuration, now=now)
        # A snooze ends the firing, as on the logs stack. A firing after it opens a new incident.
        snoozing = snooze_changed and snooze_until is not None and snooze_until > now
        edit, pending = _apply(configuration, change, now=now, snoozing=snoozing)
        if cadence is not None:
            platform_lifecycle.write_owned_cadence(configuration, cadence, rescheduled=rescheduled)
        if snooze_changed:
            platform_lifecycle.write_snooze(configuration, snooze_until, now=now)
        if first_enabled_at is not None and configuration.first_enabled_at != first_enabled_at:
            # `update()` so that correcting the stamp logs no second edit of the copy.
            PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(id=configuration.id).update(
                first_enabled_at=first_enabled_at
            )
            configuration.first_enabled_at = first_enabled_at
        control_plane.announce_after_commit(pending)
        _record_change(
            configuration,
            current,
            edit,
            previous_state=previous_state,
            snooze_changed=snooze_changed,
            snooze_until=snooze_until,
            # Only the change's own row takes the source's time. A check can land between `at` and
            # the lock, and the firings this edit ended must stay after it.
            now=at or now,
        )


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
    if spec is not None and spec.native is not None and legacy_configuration_id is None:
        delete_owned_configuration(team_id=team_id, configuration_id=configuration_id)
    elif spec is not None and spec.delete is not None and legacy_configuration_id is not None:
        spec.delete(team_id=team_id, legacy_configuration_id=legacy_configuration_id)
    else:
        raise PlatformAlertNotEditable(f"{source_kind} alerts cannot be deleted through this API.")
    return True


def delete_owned_configuration(*, team_id: int, configuration_id: UUID) -> None:
    """Deletes a configuration the platform owns whose source row is gone or never existed: closes
    its firings, then removes its destinations and deletes it. Nothing happens when it is gone.

    Runs outside any transaction, because the resolves go out first.
    """
    configurations = PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(
        id=configuration_id, owner=PlatformAlertOwner.PLATFORM
    )
    # Before the destinations go, so an incident manager still gets the resolve for an open firing.
    _close_firings_now(lambda: configurations.select_for_update().first())
    _delete_each(configurations, before_delete=lambda locked: _remove_owned_destinations(team_id, locked))


def delete_copy(*, team_id: int, legacy_configuration_id: UUID, owner: PlatformAlertOwner | None = None) -> bool:
    """Deletes the copy of a source alert, with its instances and threads. With `owner`, only a copy
    that stack owns. True when the deleted copy was the platform's, whose destinations go with it.

    Call it with the source row's delete, in its transaction or after it commits. The copy has no
    foreign key to that row, so nothing else removes it. A source removes the destinations itself
    only when this returns False, so each alert's destinations are removed once.
    """
    copies = PlatformAlertConfiguration.objects.for_team(team_id).filter(
        legacy_configuration_id=legacy_configuration_id
    )
    removed = False

    def remove_destinations(locked: list[PlatformAlertConfiguration]) -> None:
        nonlocal removed
        removed = _remove_owned_destinations(team_id, locked)

    _delete_each(copies if owner is None else copies.filter(owner=owner), before_delete=remove_destinations)
    return removed


def _remove_owned_destinations(team_id: int, locked: Sequence[PlatformAlertConfiguration]) -> bool:
    """Removes the HogFunction destinations of the configurations the platform owns, in the delete's
    transaction, so a delete that fails keeps them. True when any configuration was the platform's.

    A shadow copy's destinations are its source's, which removes them with its own row. An
    `AlertDestination` row goes with its configuration, so there is nothing to remove for it.
    """
    owned = [configuration for configuration in locked if configuration.owner == PlatformAlertOwner.PLATFORM]
    for configuration in owned:
        spec = source_configs.spec(SourceKind(configuration.source_kind))
        remove = None if spec is None or spec.native is None else spec.native.remove_destinations
        if remove is not None:
            remove(team_id=team_id, alert_id=configuration.destination_alert_id)
    return bool(owned)


def delete_orphaned_shadow_copies(
    *,
    source_kind: SourceKind,
    existing_source_ids: Callable[[Collection[UUID]], Collection[UUID]],
    dry_run: bool,
    batch_size: int = 500,
) -> int:
    """Deletes every shadow copy of `source_kind` whose source row no longer exists, and returns
    how many it deleted, or would delete with `dry_run`.

    `existing_source_ids` returns which of the given source row ids still exist. A copy is created
    only from a source row that exists, and a deleted source row cannot come back with the same id,
    so a copy found without its row stays an orphan.
    """
    # Cross-team on purpose: a one-off sweep over every copy of the kind. Each delete is scoped to
    # the copy's own team.
    copies = PlatformAlertConfiguration.objects.unscoped().filter(
        source_kind=source_kind.value, owner=PlatformAlertOwner.SOURCE, legacy_configuration_id__isnull=False
    )
    found = 0
    for batch in _pages_by_id(copies, "team_id", "legacy_configuration_id", batch_size=batch_size):
        existing = set(existing_source_ids([legacy_id for _, _, legacy_id in batch if legacy_id is not None]))
        orphans = [
            (configuration_id, team_id) for configuration_id, team_id, legacy_id in batch if legacy_id not in existing
        ]
        found += len(orphans)
        if dry_run:
            continue
        for configuration_id, team_id in orphans:
            _delete_each(
                PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(
                    id=configuration_id, owner=PlatformAlertOwner.SOURCE
                )
            )
    return found


def fill_missing_creators(
    *,
    source_kind: SourceKind,
    creators_of: Callable[[Collection[UUID]], Mapping[UUID, int]],
    dry_run: bool,
    batch_size: int = 500,
) -> int:
    """Copies `created_by` from the source rows onto every copy of `source_kind` that has none, and
    returns how many it filled, or would fill with `dry_run`.

    `creators_of` maps the given source row ids to the id of the user who created each. A row with no
    creator, or one that is gone, is left out, and its copy stays without one.
    """
    copies = PlatformAlertConfiguration.objects.unscoped().filter(
        source_kind=source_kind.value, legacy_configuration_id__isnull=False, created_by__isnull=True
    )
    filled = 0
    for batch in _pages_by_id(copies, "legacy_configuration_id", batch_size=batch_size):
        creators = creators_of([legacy_id for _, legacy_id in batch if legacy_id is not None])
        found = {
            configuration_id: creators[legacy_id] for configuration_id, legacy_id in batch if legacy_id in creators
        }
        filled += len(found)
        if found and not dry_run:
            # `copies` still requires an unset creator, so an upsert since this page was read wins.
            copies.filter(id__in=list(found)).update(
                created_by_id=Case(*(When(id=key, then=Value(user_id)) for key, user_id in found.items()))
            )
    return filled


def match_first_enabled_at(
    *,
    source_kind: SourceKind,
    team_id: int,
    first_enabled_of: Callable[[Collection[UUID]], Mapping[UUID, datetime]],
    dry_run: bool,
    batch_size: int = 500,
) -> int:
    """Sets `first_enabled_at` on each of the team's copies of `source_kind` to its source row's, where
    the two differ, and returns how many it set, or would set with `dry_run`.

    `first_enabled_of` maps the given source row ids to when each row was first turned on. A row never
    turned on, or one that is gone, is left out, and its copy stays as it is.
    """
    copies = PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(
        source_kind=source_kind.value, legacy_configuration_id__isnull=False
    )
    matched = 0
    for batch in _pages_by_id(copies, "legacy_configuration_id", "first_enabled_at", batch_size=batch_size):
        source_values = first_enabled_of([legacy_id for _, legacy_id, _ in batch])
        found = {
            configuration_id: source_values[legacy_id]
            for configuration_id, legacy_id, current in batch
            if legacy_id in source_values and source_values[legacy_id] != current
        }
        matched += len(found)
        if found and not dry_run:
            # `update()` rather than `save()`: the copy takes its source's history, which is not a user's edit.
            copies.filter(id__in=list(found)).update(
                first_enabled_at=Case(*(When(id=key, then=Value(at)) for key, at in found.items()))
            )
    return matched


def assign_native_creator(
    *, team_id: int, source_kinds: Sequence[str], configuration_id: UUID, created_by_id: int
) -> bool:
    """Makes `created_by_id` the creator of a configuration whose source keeps no row, which its checks
    run as. False when there is no such configuration. A copy's creator comes from its source's row."""
    with transaction.atomic():
        configuration = (
            PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
            .select_for_update()
            .filter(id=configuration_id, source_kind__in=list(source_kinds), legacy_configuration_id__isnull=True)
            .first()
        )
        if configuration is None:
            return False
        configuration.created_by_id = created_by_id
        configuration.save(update_fields=["created_by", "updated_at"])
    return True


def _pages_by_id(
    configurations: QuerySet[PlatformAlertConfiguration], *fields: str, batch_size: int
) -> Iterator[list[tuple[Any, ...]]]:
    """`(id, *fields)` of every configuration, a page at a time in id order.

    Paged by id rather than with `iterator()`, because PgBouncer disables server-side cursors and
    `iterator()` would then load every row at once. A row the caller changes so it stops matching
    leaves the later pages as they were.
    """
    after: UUID | None = None
    while batch := list(
        (configurations if after is None else configurations.filter(id__gt=after))
        .order_by("id")
        .values_list("id", *fields)[:batch_size]
    ):
        after = batch[-1][0]
        yield batch


def _delete_each(
    configurations: QuerySet[PlatformAlertConfiguration],
    *,
    before_delete: Callable[[list[PlatformAlertConfiguration]], object] | None = None,
) -> None:
    with transaction.atomic():
        # The configuration before its children, the order `record_outcomes` locks them in. The
        # cascade deletes the children first, so without this the two can deadlock. Each row goes
        # through the model's own delete, because a queryset delete skips the activity log.
        locked = list(configurations.select_for_update())
        if before_delete is not None:
            before_delete(locked)
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


def _record_change(
    configuration: PlatformAlertConfiguration,
    current: PlatformAlertConfigurationEdit,
    edit: PlatformAlertConfigurationEdit,
    *,
    previous_state: PlatformAlertState,
    snooze_changed: bool,
    snooze_until: datetime | None,
    now: datetime,
) -> None:
    spec = source_configs.spec(SourceKind(configuration.source_kind))
    kept = spec.kept_source_config_keys if spec is not None else frozenset()
    # Compared as `_apply` compares them for `ending_reason`, so a row and an ended firing agree.
    kind = control_plane.change_kind(
        _with_kept_keys(current, edit, kept),
        edit,
        regrouped=not edit.grouping.splits_like(current.grouping),
        snooze_changed=snooze_changed,
        snooze_until=snooze_until,
    )
    if kind is not None:
        platform_lifecycle.record_history_after_commit(
            configuration.team_id,
            [platform_lifecycle.control_change_row(configuration, kind, previous_state=previous_state, now=now)],
        )


def _with_kept_keys(
    edit: PlatformAlertConfigurationEdit, other: PlatformAlertConfigurationEdit, keys: frozenset[str]
) -> PlatformAlertConfigurationEdit:
    """`edit` with each of `keys` its `source_config` leaves out taken from `other`'s."""
    missing = {key: other.source_config[key] for key in keys - edit.source_config.keys() if key in other.source_config}
    return replace(edit, source_config={**edit.source_config, **missing}) if missing else edit


def _apply(
    configuration: PlatformAlertConfiguration,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
    *,
    now: datetime,
    snoozing: bool = False,
    admit: bool = False,
    guard: NativeEditGuard | None = None,
    check_interval_minutes: int | None = None,
) -> tuple[PlatformAlertConfigurationEdit, control_plane.PendingClose | None]:
    """Validates and writes an edit onto a configuration locked by the caller, and ends the firings it
    makes meaningless. With `admit`, the source's admission decides first on an edit that turns the
    alert on: an edit the source made on its own row has already passed its own checks. The guard and
    admission judge `check_interval_minutes` when the caller is about to change the cadence."""
    interval = configuration.check_interval_minutes if check_interval_minutes is None else check_interval_minutes
    if configuration.owner != PlatformAlertOwner.PLATFORM:
        raise PlatformAlertNotEditable(
            f"This alert is managed by the {configuration.source_kind} product. Edit it there."
        )
    source_kind = SourceKind(configuration.source_kind)
    spec = source_configs.spec(source_kind)
    kept = spec.kept_source_config_keys if spec is not None else frozenset()
    current = edit_of(configuration)
    edit = _validated(
        source_kind, current, _with_kept_keys(change(current), current, kept), team_id=configuration.team_id
    )
    if guard is not None:
        guard(
            team_id=configuration.team_id,
            current=current,
            edit=edit,
            check_interval_minutes=interval,
        )
    if admit and edit.enabled and not current.enabled:
        _admit(
            team_id=configuration.team_id,
            source_kind=source_kind,
            current=current,
            edit=edit,
            check_interval_minutes=interval,
        )

    regrouped = not edit.grouping.splits_like(current.grouping)
    ending = control_plane.ending_reason(
        _with_kept_keys(current, edit, kept), edit, regrouped=regrouped, snoozing=snoozing
    )
    # Before the instances change, so the history rows name the firings as they ran.
    pending = control_plane.end_firings(configuration, reason=ending, now=now) if ending else None

    platform_lifecycle.write_edit(configuration, edit, regrouped=regrouped, now=now)
    return edit, pending
