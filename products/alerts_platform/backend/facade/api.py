"""The shared alert tables, as a source adapter and this product's own API see them.

A source reads a batch of checks, reports what it decided, and can copy its own configurations
in. A reader asks for configurations and gets contracts. Neither ever holds one of these rows,
so every write and every scheduling rule has one home.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    AlertEventKind,
    AlertReceiverEdit,
    AlertRouteEdit,
    ControlChangeKind,
    DestinationSend,
    DestinationType,
    EnabledNativeConfiguration,
    HandbackRefusal,
    HeldDeliveryAddress,
    NativeConfigurationMatch,
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
    PlatformControlChangePage,
    PlatformControlHistory,
    PlatformHandback,
    PlatformLastCheck,
    PlatformOwnershipHandover,
    SourceKind,
    StateInterval,
    StoredAlertDestination,
    StoredAlertReceiver,
    StoredAlertRoute,
    VerdictChange,
)
from products.alerts_platform.backend.facade.enums import (
    HoldRelease,
    HoldReleasedBy,
    PlatformAlertOwner,
    PlatformAlertState,
)
from products.alerts_platform.backend.logic import (
    alert_destinations,
    alert_routing,
    delivery_holds,
    destination_sends,
    platform_lifecycle,
    platform_reads,
    platform_writes,
    state_timeline as state_timeline_logic,
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


def source_suppressed_holds_by_public_id(
    *, team_id: int, public_id: UUID, evaluation_keys: Collection[str]
) -> frozenset[str]:
    """The named evaluations of an alert the platform owns whose held delivery its source released
    with a suppress. A suppress by the safety net, for a configuration turned off, is left out."""
    return delivery_holds.source_suppressed_holds_by_public_id(team_id, public_id, evaluation_keys)


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


def upsert_if_running(upsert: PlatformAlertUpsert, *, revive: bool = False, admit_new_teams: bool = False) -> None:
    """Copy one configuration in only when its team already runs that source here.

    `revive` says the source alert was just created or turned back on, so the copy starts clean.
    `admit_new_teams` also admits a team with no enabled copy while the source runs elsewhere and
    no operator switched that team off.
    """
    platform_lifecycle.upsert_if_running(upsert, revive=revive, admit_new_teams=admit_new_teams)


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
    created_by_uuid: UUID | None = None,
) -> PlatformAlertConfigurationPage:
    """One page of configurations a caller may read, with the total behind it. With a
    `legacy_configuration_id`, only the copy of that source row. With `configuration_ids`, only those.
    With `created_by_uuid`, only the ones that user created."""
    return platform_reads.list_configurations(
        team_id=team_id,
        source_kinds=source_kinds,
        limit=limit,
        offset=offset,
        legacy_configuration_id=legacy_configuration_id,
        configuration_ids=configuration_ids,
        created_by_uuid=created_by_uuid,
    )


def native_configuration_keys(
    *, team_id: int, source_kind: SourceKind, created_by_uuid: UUID | None = None
) -> tuple[tuple[datetime, UUID], ...]:
    """`(created_at, id)` of every alert of a kind with no source row, newest first. A source that keeps
    rows for its other alerts pages the two together on these, then reads only the page with
    `list_configurations`. With `created_by_uuid`, only the ones that user created."""
    return platform_reads.native_configuration_keys(
        team_id=team_id, source_kind=source_kind.value, created_by_uuid=created_by_uuid
    )


def native_configuration_matches(
    *, team_id: int, source_kind: SourceKind, search: str | None = None
) -> tuple[NativeConfigurationMatch, ...]:
    """Every alert of a kind with no source row, with what a source's list filters, sorts and pages
    them on beside its own rows. With `search`, only the ones whose name matches it, exact and
    similar alike: the source keeps only the exact tier when any row of either kind is exact."""
    return platform_reads.native_configuration_matches(team_id=team_id, source_kind=source_kind.value, search=search)


def enabled_native_configurations(
    *,
    team_ids: Collection[int],
    source_kind: SourceKind,
    created_by_id: int | None = None,
    source_config_key: str | None = None,
    values: Collection[Any] = (),
    limit: int | None = None,
) -> tuple[EnabledNativeConfiguration, ...]:
    """The enabled alerts of a kind with no source row in these teams, newest first. With
    `created_by_id`, only the ones that user created. With `source_config_key`, only the ones whose
    `source_config[key]` is one of `values`. With `limit`, at most that many."""
    return platform_reads.enabled_native_configurations(
        team_ids=team_ids,
        source_kind=source_kind.value,
        created_by_id=created_by_id,
        source_config_key=source_config_key,
        values=values,
        limit=limit,
    )


def native_configuration_team_id(*, configuration_id: UUID, source_kind: SourceKind) -> int | None:
    """The team of an alert of a kind with no source row, or None when there is none. The caller
    authorizes against the team before it acts on the alert."""
    return platform_reads.native_configuration_team_id(configuration_id=configuration_id, source_kind=source_kind.value)


def owned_configuration_ids_without_source_rows(
    *,
    team_id: int,
    source_kind: SourceKind,
    source_config_key: str,
    values: Collection[Any],
    existing_source_ids: Callable[[Collection[UUID]], Collection[UUID]],
) -> tuple[UUID, ...]:
    """Ids of the team's alerts of a kind the platform owns whose `source_config[key]` is one of
    `values` and that have no source row, such as the alerts left on a set of deleted insights.
    `existing_source_ids` returns which of the given source row ids still exist."""
    return platform_reads.owned_configuration_ids_without_source_rows(
        team_id=team_id,
        source_kind=source_kind.value,
        source_config_key=source_config_key,
        values=values,
        existing_source_ids=existing_source_ids,
    )


def count_configurations(
    *,
    team_id: int,
    source_kind: SourceKind,
    native_only: bool = False,
    enabled_only: bool = False,
    check_interval_minutes: int | None = None,
    exclude_id: UUID | None = None,
    source_config_contains: Mapping[str, Any] | None = None,
) -> int:
    """How many alerts of a kind a team has on the platform. For a source's admission. With
    `exclude_id`, the alert an edit is checked for is left out.

    A source that keeps rows counts them and adds `native_only`. A copy stands for a row the source
    already counts, and a copy left by a delete from before copies went with their row counts nothing.
    """
    return platform_reads.count_configurations(
        team_id=team_id,
        source_kind=source_kind.value,
        native_only=native_only,
        enabled_only=enabled_only,
        check_interval_minutes=check_interval_minutes,
        exclude_id=exclude_id,
        source_config_contains=source_config_contains,
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


def control_changes_by_public_id(
    *, team_id: int, public_id: UUID, kinds: Collection[ControlChangeKind], limit: int
) -> PlatformControlChangePage | None:
    """The newest `limit` control-plane changes of `kinds` to a named alert, with their total and the
    time of the oldest change of any kind, or None when the platform does not own the alert.

    Raises when ClickHouse fails, so a caller can fall back to what it shows without the platform.
    """
    return platform_reads.control_changes_by_public_id(team_id=team_id, public_id=public_id, kinds=kinds, limit=limit)


def control_history_by_public_id(
    *, team_id: int, public_ids: Collection[UUID], since: datetime, until: datetime
) -> dict[UUID, PlatformControlHistory]:
    """The control-plane changes in `[since, until)` of each named alert the platform owns, keyed by its
    public id, with when its oldest kept change happened and its newest enable or disable before `since`.

    Raises when ClickHouse fails, so a caller can fall back to what it shows without the platform.
    """
    return platform_reads.control_history_by_public_id(team_id=team_id, public_ids=public_ids, since=since, until=until)


def state_timeline(
    *,
    history: PlatformAlertHistory | None,
    control: PlatformControlHistory | None,
    current_state: PlatformAlertState,
    current_enabled: bool,
    window: tuple[datetime, datetime],
) -> tuple[StateInterval, ...]:
    """An alert's state over `window` from its check history and control-plane changes, oldest first."""
    return state_timeline_logic.state_timeline(
        history=history,
        control=control,
        current_state=current_state,
        current_enabled=current_enabled,
        window=window,
    )


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
    """Applies an edit to a configuration the platform owns, or None when the caller cannot read it.
    With `snooze_changed`, `snooze_until` becomes the whole alert's mute, and None clears it.

    For an alert with no source row, `cadence` and `rescheduled` write its schedule as
    `update_owned_copy` writes a copy's. Its kind's `native_edit_guard` refuses what only the
    source's API may change, unless `source_checked` says the source's API made the edit.

    Raises `PlatformAlertNotEditable` for a configuration its source owns, and
    `InvalidPlatformAlertEdit` for an edit its source kind rejects.
    """
    return platform_writes.update_configuration(
        team_id=team_id,
        source_kinds=source_kinds,
        configuration_id=configuration_id,
        change=change,
        snooze_until=snooze_until,
        snooze_changed=snooze_changed,
        cadence=cadence,
        rescheduled=rescheduled,
        source_checked=source_checked,
    )


def create_configuration(
    *,
    team_id: int,
    source_kind: SourceKind,
    edit: PlatformAlertConfigurationEdit,
    created_by_id: int | None,
    natively: bool | None = None,
) -> PlatformAlertConfigurationView:
    """Creates an alert the platform owns, with its source's own row when the source keeps one. With
    `natively`, the caller decides whether that row is skipped.

    Raises `PlatformAlertNotEditable` for a kind the API cannot create, `InvalidPlatformAlertEdit` for
    settings its source kind rejects, and `PlatformAlertCreateRefused` when the source refuses.
    """
    return platform_writes.create_configuration(
        team_id=team_id, source_kind=source_kind, edit=edit, created_by_id=created_by_id, natively=natively
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
    at: datetime | None = None,
) -> None:
    """Applies an edit a source made to its own row onto the copy the platform owns. When `cadence`
    changes the copy's cadence, or `rescheduled` says the source moved its own due time, the copy is
    next due at the cadence's `next_check_at`. `at` is when the source made the edit, taken before
    it wrote any history row of its own, so the platform's row of the same change is no later.

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
        at=at,
    )


def assign_native_creator(
    *, team_id: int, source_kinds: Sequence[str], configuration_id: UUID, created_by_id: int
) -> bool:
    """Makes `created_by_id` the creator of a configuration whose source keeps no row, which its checks
    run as. False when there is no such configuration."""
    return platform_writes.assign_native_creator(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id, created_by_id=created_by_id
    )


def delete_configuration(*, team_id: int, source_kinds: Sequence[str], configuration_id: UUID) -> bool:
    """Deletes a configuration the platform owns, with its source's own row. False when the caller
    cannot read it.

    Raises `PlatformAlertNotEditable` for a configuration its source owns, or of a kind the API cannot delete.
    """
    return platform_writes.delete_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id
    )


def delete_copy(*, team_id: int, legacy_configuration_id: UUID, owner: PlatformAlertOwner | None = None) -> bool:
    """Deletes the copy of a source alert with the source row, in its transaction or after it
    commits. With `owner`, only a copy that stack owns.

    True when the copy was the platform's: its HogFunction destinations went with it, and the source
    must not remove them again.
    """
    return platform_writes.delete_copy(team_id=team_id, legacy_configuration_id=legacy_configuration_id, owner=owner)


def delete_owned_configuration(*, team_id: int, configuration_id: UUID) -> None:
    """Deletes a configuration the platform owns whose source row is gone or never existed, after
    sending the resolves of its open firings. Call it outside any transaction."""
    platform_writes.delete_owned_configuration(team_id=team_id, configuration_id=configuration_id)


def delete_orphaned_shadow_copies(
    *,
    source_kind: SourceKind,
    existing_source_ids: Callable[[Collection[UUID]], Collection[UUID]],
    dry_run: bool,
) -> int:
    """Deletes the shadow copies of `source_kind` whose source row is gone, and returns the count.
    `existing_source_ids` returns which of the given source row ids still exist."""
    return platform_writes.delete_orphaned_shadow_copies(
        source_kind=source_kind, existing_source_ids=existing_source_ids, dry_run=dry_run
    )


def fill_missing_creators(
    *, source_kind: SourceKind, creators_of: Callable[[Collection[UUID]], Mapping[UUID, int]], dry_run: bool
) -> int:
    """Copies `created_by` from the source rows onto the copies of `source_kind` that have none, and
    returns the count. `creators_of` maps the given source row ids to their creators' user ids."""
    return platform_writes.fill_missing_creators(source_kind=source_kind, creators_of=creators_of, dry_run=dry_run)


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


def set_subscriber_destinations(
    *,
    team_id: int,
    public_id: UUID,
    user_ids: Collection[int],
    event_kinds: Collection[AlertEventKind],
    in_app_resource_type: str,
    in_app_resource_id: str,
) -> bool:
    """Replaces the email and in-app destinations that name the alert's subscribers. False when the
    platform has no alert under `public_id`, such as an insight alert never copied."""
    return alert_destinations.set_subscriber_destinations(
        team_id=team_id,
        public_id=public_id,
        user_ids=user_ids,
        event_kinds=event_kinds,
        in_app_resource_type=in_app_resource_type,
        in_app_resource_id=in_app_resource_id,
    )


def remove_subscriber(*, team_ids: Collection[int], user_id: int) -> int:
    """Takes a user who left an organization out of every subscriber destination of its teams' alerts,
    and returns how many alerts named them."""
    return alert_destinations.remove_subscriber(team_ids=team_ids, user_id=user_id)


def subscriber_user_ids_by_public_id(*, team_id: int, public_ids: Collection[UUID]) -> dict[UUID, tuple[int, ...]]:
    """The subscribers each alert's destinations name, by public id. An alert with no subscriber
    destination is left out, which is not the same as one whose subscribers all left."""
    return alert_destinations.subscriber_user_ids_by_public_id(team_id=team_id, public_ids=public_ids)


def list_alert_destinations(*, team_id: int, configuration_id: UUID) -> tuple[StoredAlertDestination, ...]:
    return alert_destinations.list_alert_destinations(team_id=team_id, configuration_id=configuration_id)


def destination_types_by_configuration(
    *, team_id: int, configuration_ids: Collection[UUID]
) -> dict[UUID, tuple[str, ...]]:
    """The types of each named configuration's enabled destinations, for an alert list. A configuration
    with none is left out."""
    return alert_destinations.destination_types_by_configuration(team_id=team_id, configuration_ids=configuration_ids)


def redact_destination_data(data: AlertDestinationData) -> AlertDestinationData:
    """A destination's configuration without the parts that are a credential, for showing it."""
    return alert_destinations.redact_destination_data(data)


def has_incident_destination(*, team_id: int, configuration_id: UUID) -> bool:
    """Whether an alert whose destinations the platform owns has an enabled incident manager."""
    return alert_destinations.has_incident_destination(team_id=team_id, configuration_id=configuration_id)


def destination_hears_kind(
    *, team_id: int, configuration_id: UUID, destination_type: DestinationType, event_kind: AlertEventKind
) -> bool:
    """Whether an enabled destination of this type that the platform keeps for the alert sends this kind."""
    return alert_destinations.hears_kind(
        team_id=team_id, configuration_id=configuration_id, destination_type=destination_type, event_kind=event_kind
    )


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


def list_alert_receivers(*, team_id: int) -> tuple[StoredAlertReceiver, ...]:
    return alert_routing.list_receivers(team_id=team_id)


def create_alert_receiver(*, team_id: int, edit: AlertReceiverEdit) -> StoredAlertReceiver:
    """Raises `AlertDestinationValidationError` on a refused receiver."""
    return alert_routing.create_receiver(team_id=team_id, edit=edit)


def update_alert_receiver(*, team_id: int, receiver_id: UUID, edit: AlertReceiverEdit) -> StoredAlertReceiver:
    """Raises `UnknownAlertRouting` for an id the team has no receiver with."""
    return alert_routing.update_receiver(team_id=team_id, receiver_id=receiver_id, edit=edit)


def delete_alert_receiver(*, team_id: int, receiver_id: UUID) -> None:
    """Deletes the receiver and its routes. Raises `UnknownAlertRouting` for an id the team has no receiver with."""
    alert_routing.delete_receiver(team_id=team_id, receiver_id=receiver_id)


def list_alert_routes(*, team_id: int) -> tuple[StoredAlertRoute, ...]:
    return alert_routing.list_routes(team_id=team_id)


def create_alert_route(*, team_id: int, edit: AlertRouteEdit) -> StoredAlertRoute:
    return alert_routing.create_route(team_id=team_id, edit=edit)


def update_alert_route(*, team_id: int, route_id: UUID, edit: AlertRouteEdit) -> StoredAlertRoute:
    """Raises `UnknownAlertRouting` for an id the team has no route with."""
    return alert_routing.update_route(team_id=team_id, route_id=route_id, edit=edit)


def delete_alert_route(*, team_id: int, route_id: UUID) -> None:
    """Raises `UnknownAlertRouting` for an id the team has no route with."""
    alert_routing.delete_route(team_id=team_id, route_id=route_id)
