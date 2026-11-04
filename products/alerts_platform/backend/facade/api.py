"""The shared alert tables, as a source adapter and this product's own API see them.

A source reads a batch of checks, reports what it decided, and can copy its own configurations
in. A reader asks for configurations and gets contracts. Neither ever holds one of these rows,
so every write and every scheduling rule has one home.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    DestinationSend,
    HandbackRefusal,
    HeldDeliveryAddress,
    NewAlertDestination,
    PlatformAlertCheckInput,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationPage,
    PlatformAlertConfigurationView,
    PlatformAlertHistory,
    PlatformAlertOutcome,
    PlatformAlertRuntime,
    PlatformAlertSnapshot,
    PlatformAlertUpsert,
    PlatformCheckEntry,
    PlatformCheckEventPage,
    PlatformCheckPage,
    PlatformHandback,
    PlatformLastCheck,
    PlatformOwnershipHandover,
    SourceKind,
    StoredAlertDestination,
    VerdictChange,
)
from products.alerts_platform.backend.facade.enums import HoldRelease, HoldReleasedBy
from products.alerts_platform.backend.logic import (
    alert_destinations,
    delivery_holds,
    destination_sends,
    platform_lifecycle,
    platform_reads,
    platform_writes,
    verdict_changes,
)


def due_checks(
    team_id: int, source_kind: str, slot: str, cutoff: datetime, *, configuration_ids: Collection[str] | None = None
) -> tuple[PlatformAlertCheckInput, ...]:
    """Every check one batch key owes, flattened as a source reads them, or only the named ones."""
    return platform_lifecycle.due_checks(team_id, source_kind, slot, cutoff, configuration_ids=configuration_ids)


def due_check_ids(
    team_id: int, source_kind: str, slot: str, cutoff: datetime, *, exclude: Collection[str] = (), limit: int
) -> tuple[str, ...]:
    """The first `limit` due ids of one batch key, skipping `exclude`, without their runtime state."""
    return platform_lifecycle.due_check_ids(team_id, source_kind, slot, cutoff, exclude=exclude, limit=limit)


def record_outcomes(team_id: int, outcomes: Sequence[PlatformAlertOutcome], now: datetime) -> int:
    """The platform's only write of state and schedule. Returns how many rows it wrote."""
    return platform_lifecycle.record_outcomes(team_id, outcomes, now)


def release_hold(
    address: HeldDeliveryAddress, *, action: HoldRelease, released_by: HoldReleasedBy, now: datetime
) -> AlertDeliveryRequest | None:
    """Releases a held delivery. Returns the request when the caller should start its delivery,
    which it does with `start_deliveries` so the delivery keeps its usual id."""
    return delivery_holds.release_hold(address, action=action, released_by=released_by, now=now)


def record_hold_delivery_started(address: HeldDeliveryAddress, *, now: datetime) -> None:
    """Marks a released send's delivery as started. Call it after `start_deliveries` returns, or the
    safety net starts the delivery again once a grace period passes, and the delivery's id dedups it."""
    delivery_holds.record_delivery_started([address], now)


def reschedule_hold(address: HeldDeliveryAddress, *, release_after: datetime) -> bool:
    """Moves an unreleased hold's safety-net deadline. Returns False when nothing was held."""
    return delivery_holds.reschedule_hold(address, release_after=release_after)


def source_suppressed_holds_by_legacy_id(
    *, team_id: int, legacy_configuration_id: UUID, evaluation_keys: Collection[str]
) -> frozenset[str]:
    """The named evaluations of an alert the platform owns whose held delivery its source released
    with a suppress. A suppress by the safety net, for a configuration turned off, is left out."""
    return delivery_holds.source_suppressed_holds_by_legacy_id(team_id, legacy_configuration_id, evaluation_keys)


def record_verdict_change(change: VerdictChange, *, now: datetime) -> AlertDeliveryRequest | None:
    """Records one follow-up about a firing that already went out, and returns the delivery to start
    with `start_deliveries`, or None when there is nothing to send.

    Writes only the follow-up's history row, so it leaves state, schedule and holds alone. A second
    call for the same firing starts the same delivery, whose id and threads send it once. Raises
    `VerdictChangeNotRecorded` when the row could not be written, which a retry can recover.
    """
    return verdict_changes.record_verdict_change(change, now=now)


def delivery_held_back(address: HeldDeliveryAddress) -> bool:
    """Whether an evaluation's delivery is held and not released with a send, so it has not gone out."""
    return delivery_holds.blocks_delivery(address.team_id, address.configuration_id, address.evaluation_key)


def record_verdict_changed(
    address: HeldDeliveryAddress, *, episode_started_at: datetime | None, now: datetime
) -> AlertDeliveryRequest | None:
    """Announces that a source's later verdict contradicts the one a delivered firing carried, in
    that firing's thread. Returns the request the caller starts, or None when nothing is to be sent.

    Records nothing and returns None until the source can word a follow-up, which
    `record_verdict_change` then records and delivers.
    """
    return None


def hold_released_by(address: HeldDeliveryAddress) -> HoldReleasedBy | None:
    """Who released an evaluation's held delivery, so a source can word the message that the release sent.
    None when the evaluation was never held or is still held."""
    return delivery_holds.hold_released_by(address)


def slot_of(next_check_at: datetime | None, cutoff: datetime) -> str:
    """The minute a configuration is due for."""
    return platform_lifecycle.slot_of(next_check_at, cutoff)


def upsert_configuration(upsert: PlatformAlertUpsert, *, revive: bool = False) -> bool:
    """Copy one of a source's own configurations in. True when it created the row."""
    return platform_lifecycle.upsert_configuration(upsert, revive=revive)


def upsert_if_running(upsert: PlatformAlertUpsert, *, revive: bool = False) -> None:
    """Copy one configuration in only when its team already runs that source here.

    `revive` says the source alert was just created or turned back on, so the copy starts clean.
    """
    platform_lifecycle.upsert_if_running(upsert, revive=revive)


def refresh_settings(team_id: int, configuration_id: UUID, upsert: PlatformAlertUpsert) -> None:
    """Write a source's current settings onto its copy, leaving the schedule and state alone."""
    platform_lifecycle.refresh_settings(team_id, configuration_id, upsert)


def take_ownership(handover: PlatformOwnershipHandover) -> bool:
    """Makes the platform the owner of a copied alert, carrying on from the source's state."""
    return platform_lifecycle.take_ownership(handover)


def give_back_ownership(
    *, team_id: int, legacy_configuration_id: UUID, at: datetime, source_runs_calendar_schedules: bool = False
) -> PlatformHandback | HandbackRefusal:
    """Hands a copied alert back to its source, or says why the platform keeps it."""
    return platform_lifecycle.give_back_ownership(
        team_id=team_id,
        legacy_configuration_id=legacy_configuration_id,
        at=at,
        source_runs_calendar_schedules=source_runs_calendar_schedules,
    )


def reset_broken(*, team_id: int, public_id: UUID, at: datetime) -> int | None:
    """Clears a broken alert the platform owns. Returns the failure count it cleared, or None when not broken."""
    return platform_lifecycle.reset_broken(team_id=team_id, public_id=public_id, at=at)


def disable_configurations(
    source_kind: SourceKind, *, team_id: int | None = None, legacy_configuration_ids: Collection[UUID] | None = None
) -> int:
    """Switch off a source's copies, or one team's, or the copies of named source alerts. Returns how many it switched off."""
    return platform_lifecycle.disable_configurations(
        source_kind.value, team_id=team_id, legacy_configuration_ids=legacy_configuration_ids
    )


def list_configurations(
    *,
    team_id: int,
    source_kinds: Sequence[str],
    limit: int,
    offset: int,
    legacy_configuration_id: UUID | None = None,
    configuration_ids: Collection[UUID] | None = None,
) -> PlatformAlertConfigurationPage:
    """One page of configurations a caller may read, with the total behind it. With a
    `legacy_configuration_id`, only the copy of that source row. With `configuration_ids`, only those."""
    return platform_reads.list_configurations(
        team_id=team_id,
        source_kinds=source_kinds,
        limit=limit,
        offset=offset,
        legacy_configuration_id=legacy_configuration_id,
        configuration_ids=configuration_ids,
    )


def count_configurations(
    *,
    team_id: int,
    source_kind: SourceKind,
    native_only: bool = False,
    enabled_only: bool = False,
    check_interval_minutes: int | None = None,
) -> int:
    """How many alerts of a kind a team has on the platform. For a source's admission.

    A source that keeps rows counts them and adds `native_only`, because a copy outlives its source
    row when the source deletes an alert the platform does not own.
    """
    return platform_reads.count_configurations(
        team_id=team_id,
        source_kind=source_kind.value,
        native_only=native_only,
        enabled_only=enabled_only,
        check_interval_minutes=check_interval_minutes,
    )


def hold_cap_lock(*, team_id: int, source_kind: SourceKind) -> None:
    """The lock the platform holds while a source checks its caps, for a source creating an alert
    outside the platform. Call it inside the create's transaction."""
    platform_writes.hold_cap_lock(team_id, source_kind)


def get_configuration(
    *, team_id: int, source_kinds: Sequence[str], configuration_id: UUID, lock: bool = False
) -> PlatformAlertConfigurationView | None:
    """One configuration, or None when it does not exist or the caller may not read its kind.

    With `lock`, call it inside a transaction: the row stays locked until it ends, so a delete waits.
    """
    return platform_reads.get_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id, lock=lock
    )


def runtime_by_public_id(*, team_id: int, public_ids: Collection[UUID]) -> dict[UUID, PlatformAlertRuntime]:
    """The runtime state of each named alert the platform owns, keyed by its public id."""
    return platform_reads.runtime_by_public_id(team_id=team_id, public_ids=public_ids)


def check_page_by_public_id(
    *, team_id: int, public_id: UUID, since: datetime, until: datetime, limit: int, offset: int
) -> PlatformCheckPage | None:
    """A page of one owned alert's checks in a window, newest first, or None when the platform does not own it.

    Raises when ClickHouse fails, so a caller can fall back to what it shows without the platform.
    """
    return platform_reads.check_page_by_public_id(
        team_id=team_id,
        public_id=public_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


def checks_with_detail_by_public_id(
    *,
    team_id: int,
    public_ids: Collection[UUID],
    detail_paths: Sequence[Sequence[str]],
    since: datetime,
    limit: int,
) -> dict[UUID, tuple[PlatformCheckEntry, ...]]:
    """Each named owned alert's newest `limit` checks since `since` whose source detail holds
    every one of `detail_paths`, newest first, keyed by its public id.

    Raises when ClickHouse fails, so a caller can fall back to what it shows without the platform.
    """
    return platform_reads.checks_with_detail_by_public_id(
        team_id=team_id,
        public_ids=public_ids,
        detail_paths=detail_paths,
        since=since,
        limit=limit,
    )


def history_by_public_id(
    *, team_id: int, public_ids: Collection[UUID], since: datetime, until: datetime
) -> dict[UUID, PlatformAlertHistory]:
    """The check history in a window of each named alert the platform owns, keyed by its public id.

    Raises when ClickHouse fails, so a caller can fall back to what it shows without the platform.
    """
    return platform_reads.history_by_public_id(team_id=team_id, public_ids=public_ids, since=since, until=until)


def last_check_by_public_id(*, team_id: int, public_ids: Collection[UUID]) -> dict[UUID, PlatformLastCheck]:
    """The newest check of each named alert the platform owns, keyed by its public id.

    Raises when ClickHouse fails, so a caller can fall back to what it shows without the platform.
    """
    return platform_reads.last_check_by_public_id(team_id=team_id, public_ids=public_ids)


def notable_checks_by_public_id(
    *, team_id: int, public_id: UUID, since: datetime, limit: int
) -> PlatformCheckEventPage | None:
    """The newest `limit` checks since `since` that moved a named alert's state or failed, with
    their total, or None when the platform does not own the alert.

    Raises when ClickHouse fails, so a caller can fall back to what it shows without the platform.
    """
    return platform_reads.notable_checks_by_public_id(team_id=team_id, public_id=public_id, since=since, limit=limit)


def update_configuration(
    *,
    team_id: int,
    source_kinds: Sequence[str],
    configuration_id: UUID,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
) -> PlatformAlertConfigurationView | None:
    """Applies an edit to a configuration the platform owns, or None when the caller cannot read it.

    Raises `PlatformAlertNotEditable` for a configuration its source owns, and
    `InvalidPlatformAlertEdit` for an edit its source kind rejects.
    """
    return platform_writes.update_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id, change=change
    )


def create_configuration(
    *, team_id: int, source_kind: SourceKind, edit: PlatformAlertConfigurationEdit, created_by_id: int | None
) -> PlatformAlertConfigurationView:
    """Creates an alert the platform owns, with its source's own row when the source keeps one.

    Raises `PlatformAlertNotEditable` for a kind the API cannot create, `InvalidPlatformAlertEdit` for
    settings its source kind rejects, and `PlatformAlertCreateRefused` when the source refuses.
    """
    return platform_writes.create_configuration(
        team_id=team_id, source_kind=source_kind, edit=edit, created_by_id=created_by_id
    )


def snooze_group(
    *,
    team_id: int,
    source_kinds: Sequence[str],
    configuration_id: UUID,
    grouping_key: str,
    snooze_until: datetime | None,
) -> PlatformAlertSnapshot | None:
    """Mutes one group of a configuration the platform owns until `snooze_until`, or clears the mute
    when it is None. Returns the group, or None when the caller cannot read the configuration.

    Raises `PlatformAlertNotEditable` for a configuration its source owns, `UnknownPlatformAlertGroup`
    for a key with no instance, and `InvalidPlatformAlertEdit` for a time not in the future or an
    alert that is not grouped.
    """
    return platform_writes.snooze_group(
        team_id=team_id,
        source_kinds=source_kinds,
        configuration_id=configuration_id,
        grouping_key=grouping_key,
        snooze_until=snooze_until,
    )


def update_owned_copy(
    *,
    team_id: int,
    legacy_configuration_id: UUID,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
    snooze_until: datetime | None = None,
    snooze_changed: bool = False,
    cadence: PlatformAlertUpsert | None = None,
    rescheduled: bool = False,
) -> None:
    """Applies an edit a source made to its own row onto the copy the platform owns. When `cadence`
    changes the copy's cadence, or `rescheduled` says the source moved its own due time, the copy is
    next due at the cadence's `next_check_at`.

    Raises `InvalidPlatformAlertEdit` for an edit the source kind's schema rejects.
    """
    platform_writes.update_owned_copy(
        team_id=team_id,
        legacy_configuration_id=legacy_configuration_id,
        change=change,
        snooze_until=snooze_until,
        snooze_changed=snooze_changed,
        cadence=cadence,
        rescheduled=rescheduled,
    )


def delete_configuration(*, team_id: int, source_kinds: Sequence[str], configuration_id: UUID) -> bool:
    """Deletes a configuration the platform owns, with its source's own row. False when the caller
    cannot read it.

    Raises `PlatformAlertNotEditable` for a configuration its source owns, or of a kind the API cannot delete.
    """
    return platform_writes.delete_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id
    )


def delete_owned_copy(*, team_id: int, legacy_configuration_id: UUID) -> None:
    platform_writes.delete_owned_copy(team_id=team_id, legacy_configuration_id=legacy_configuration_id)


def close_owned_firings_now(*, team_id: int, legacy_configuration_id: UUID) -> None:
    """Ends the firings of a copy the platform owns and sends their incident resolves before returning,
    for a delete that is about to remove the destinations."""
    platform_writes.close_owned_firings_now(team_id=team_id, legacy_configuration_id=legacy_configuration_id)


def create_alert_destinations(
    *, team_id: int, configuration_id: UUID, destinations: Sequence[NewAlertDestination]
) -> tuple[StoredAlertDestination, ...]:
    """Adds destinations to one alert, all or none. Raises `AlertDestinationValidationError` on a refused one."""
    return alert_destinations.create_alert_destinations(
        team_id=team_id, configuration_id=configuration_id, destinations=destinations
    )


def list_alert_destinations(*, team_id: int, configuration_id: UUID) -> tuple[StoredAlertDestination, ...]:
    return alert_destinations.list_alert_destinations(team_id=team_id, configuration_id=configuration_id)


def has_incident_destination(*, team_id: int, configuration_id: UUID) -> bool:
    """Whether an alert whose destinations the platform owns has an enabled incident manager."""
    return alert_destinations.has_incident_destination(team_id=team_id, configuration_id=configuration_id)


def delete_alert_destinations(*, team_id: int, configuration_id: UUID, destination_ids: Collection[UUID]) -> int:
    """Deletes the named destinations of one alert. An id of another alert is left alone."""
    return alert_destinations.delete_alert_destinations(
        team_id=team_id, configuration_id=configuration_id, destination_ids=destination_ids
    )


def recent_destination_sends(
    *, team_id: int, destination_ids: Collection[str], limit: int
) -> tuple[DestinationSend, ...]:
    """The newest sends to the named destination HogFunctions, on both delivery paths, newest first."""
    return destination_sends.recent_destination_sends(team_id=team_id, destination_ids=destination_ids, limit=limit)
