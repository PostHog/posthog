"""Writes to a configuration through the API, for the configurations the platform owns.

A configuration its source owns is a copy of the source's own row, which the source's API writes
and the next check reads back. Writing the copy here would fork it, so those are refused.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone as django_timezone

from pydantic import ValidationError as PydanticValidationError

from posthog.exceptions_capture import capture_exception

from products.alerts_platform.backend.facade.contracts import (
    MAX_EVALUATION_PERIODS,
    MAX_STORED_INTEGER,
    Grouping,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    PlatformAlertNotEditable,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.facade.scheduling import validate_and_normalize_schedule_restriction
from products.alerts_platform.backend.logic import control_plane, platform_lifecycle, platform_reads, source_configs
from products.alerts_platform.backend.models import PlatformAlertConfiguration


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
    )


def _validated(
    source_kind: SourceKind, current: PlatformAlertConfigurationEdit, edit: PlatformAlertConfigurationEdit
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
    source_config = edit.source_config
    # Settings the edit leaves alone may predate the schema, and must not block an unrelated change.
    if source_config != current.source_config:
        try:
            parsed = spec.model.model_validate(source_config)
        except PydanticValidationError as error:
            first = error.errors()[0]
            location = ".".join(str(part) for part in first["loc"])
            raise InvalidPlatformAlertEdit("source_config", f"Invalid at `{location}`: {first['msg']}") from error
        source_config = parsed.model_dump(mode="json", exclude_unset=True)
    validated = replace(edit, source_config=source_config, schedule_restriction=schedule_restriction)
    spec.validate(validated)
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
    with transaction.atomic():
        configuration = _locked_owned_copy(team_id, legacy_configuration_id)
        pending = (
            None
            if configuration is None
            else control_plane.end_firings(configuration, reason="deleted", now=django_timezone.now())
        )
    control_plane.announce_now(pending)


def delete_owned_copy(*, team_id: int, legacy_configuration_id: UUID) -> None:
    """Deletes the copy of a source alert the platform owns, with its instances and threads."""
    copies = PlatformAlertConfiguration.objects.for_team(team_id).filter(
        legacy_configuration_id=legacy_configuration_id, owner=PlatformAlertOwner.PLATFORM
    )
    with transaction.atomic():
        # The configuration before its children, the order `record_outcomes` locks them in. The
        # cascade deletes the children first, so without this the two can deadlock.
        list(copies.select_for_update())
        copies.delete()


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
    edit = _validated(SourceKind(configuration.source_kind), current, change(current))

    regrouped = not edit.grouping.splits_like(current.grouping)
    ending = control_plane.ending_reason(current, edit, regrouped=regrouped, snoozing=snoozing)
    # Before the instances change, so the history rows name the firings as they ran.
    pending = control_plane.end_firings(configuration, reason=ending, now=now) if ending else None

    platform_lifecycle.write_edit(configuration, edit, regrouped=regrouped, now=now)
    return edit, pending
