import json
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.db import connections, router, transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.customer_analytics.backend.facade.temporal_contracts import AccountPropertySyncWork
from products.customer_analytics.backend.logic.account_property_sync_generation import (
    get_account_property_sync_generation,
)
from products.customer_analytics.backend.logic.custom_property_values import (
    guard_custom_property_value,
    set_synced_custom_property_value,
)
from products.customer_analytics.backend.models import (
    AccountPropertySyncPublication,
    AccountPropertySyncRequest,
    AccountPropertySyncState,
    AccountPropertySyncValueState,
    CustomPropertySource,
)


class AccountPropertySyncSuperseded(Exception):
    pass


class AccountPropertySyncReadChanged(Exception):
    pass


@frozen
class AccountPropertySyncRead:
    team_id: int
    saved_query_id: str
    generation: int
    snapshot_revision: int = 0
    request_id: str | None = None
    token: str | None = None
    segment: str | None = None


def account_property_coordination_enabled() -> bool:
    return settings.ACCOUNT_PROPERTY_SYNC_COORDINATION_ENABLED


def get_source_mapping_key(source: CustomPropertySource) -> str:
    mapping = [
        str(source.saved_query_id),
        source.key_column,
        source.source_column,
        source.definition.display_type,
        source.definition.options,
    ]
    return hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest()


def _get_state(team_id: int, saved_query_id: str, *, lock: bool = True) -> AccountPropertySyncState:
    team_id = resolve_effective_team_id(team_id)
    states = AccountPropertySyncState.objects.for_team(team_id).using(router.db_for_write(AccountPropertySyncState))
    state, _ = states.get_or_create(team_id=team_id, saved_query_id=saved_query_id)
    return states.select_for_update().get(id=state.id) if lock else state


def record_account_property_publication(*, team_id: int, saved_query_id: str, job_id: str) -> bool:
    if not account_property_coordination_enabled():
        return True
    team_id = resolve_effective_team_id(team_id)
    sources = (
        CustomPropertySource.objects.for_team(team_id)
        .using(router.db_for_write(CustomPropertySource))
        .filter(saved_query_id=saved_query_id, source_column__isnull=False)
    )
    has_enabled_sources = sources.filter(is_enabled=True).exists()
    if (
        not has_enabled_sources
        and not sources.exists()
        and not (
            AccountPropertySyncState.objects.for_team(team_id)
            .using(router.db_for_write(AccountPropertySyncState))
            .filter(saved_query_id=saved_query_id)
            .exists()
        )
    ):
        return True
    with transaction.atomic():
        state = _get_state(team_id, saved_query_id)
        publication = (
            AccountPropertySyncPublication.objects.for_team(team_id)
            .filter(saved_query_id=saved_query_id, job_id=job_id)
            .first()
        )
        if publication is not None:
            return publication.revision == state.publication_revision
        state.publication_revision += 1
        state.save(update_fields=["publication_revision"])
        AccountPropertySyncPublication.objects.for_team(team_id).create(
            team_id=team_id, saved_query_id=saved_query_id, job_id=job_id, revision=state.publication_revision
        )
        if has_enabled_sources:
            request_account_property_sync(team_id=team_id, saved_query_id=saved_query_id)
        return True


def assert_account_property_sync_read_current(read: AccountPropertySyncRead) -> None:
    revision = (
        AccountPropertySyncState.objects.for_team(read.team_id)
        .using(router.db_for_write(AccountPropertySyncState))
        .filter(saved_query_id=read.saved_query_id)
        .values_list("publication_revision", flat=True)
        .first()
    )
    if (revision or 0) != read.snapshot_revision:
        raise AccountPropertySyncReadChanged()


def request_account_property_sync(*, team_id: int, saved_query_id: str, job_id: str | None = None) -> str:
    binding_team_id = team_id
    team_id = resolve_effective_team_id(team_id)
    with transaction.atomic():
        state = _get_state(team_id, saved_query_id)
        snapshot_revision = (
            AccountPropertySyncPublication.objects.for_team(team_id)
            .filter(saved_query_id=saved_query_id, job_id=job_id)
            .values_list("revision", flat=True)
            .first()
            if job_id is not None
            else state.publication_revision
        )
        if job_id is None and state.pending_live_request_id is not None:
            return str(state.pending_live_request_id)
        request, _ = AccountPropertySyncRequest.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            saved_query_id=saved_query_id,
            job_id=job_id or f"account-property-live-{uuid4()}",
            defaults={
                "binding_team_id": binding_team_id,
                "kind": AccountPropertySyncRequest.Kind.STAGED if job_id else AccountPropertySyncRequest.Kind.LIVE,
                "snapshot_revision": snapshot_revision or 0,
            },
        )
        if job_id is None:
            state.pending_live_request_id = request.id
            state.save(update_fields=["pending_live_request_id"])
        return str(request.id)


def get_next_account_property_sync(*, team_id: int, saved_query_id: str) -> AccountPropertySyncWork | None:
    team_id = resolve_effective_team_id(team_id)
    requests = (
        AccountPropertySyncRequest.objects.for_team(team_id)
        .using(router.db_for_write(AccountPropertySyncRequest))
        .filter(saved_query_id=saved_query_id)
    )
    while True:
        state = _get_state(team_id, saved_query_id, lock=False)
        request_id = state.active_request_id or (
            requests.filter(status=AccountPropertySyncRequest.Status.PENDING)
            .order_by("created_at", "id")
            .values_list("id", flat=True)
            .first()
        )
        if request_id is None:
            return None
        with transaction.atomic():
            # Request locks precede state locks because terminal outcomes also lock source rows.
            request = requests.select_for_update().get(id=request_id)
            state = _get_state(team_id, saved_query_id)
            if state.active_request_id is not None and state.active_request_id != request.id:
                continue
            if request.status not in {
                AccountPropertySyncRequest.Status.PENDING,
                AccountPropertySyncRequest.Status.RUNNING,
            }:
                if state.active_request_id == request.id:
                    state.active_request_id = None
                    state.save(update_fields=["active_request_id"])
                continue
            if request.status == AccountPropertySyncRequest.Status.PENDING:
                state.generation = get_account_property_sync_generation()
                state.active_request_id = request.id
                if state.pending_live_request_id == request.id:
                    state.pending_live_request_id = None
                request.generation = state.generation
                request.started_at = timezone.now()
                request.status = AccountPropertySyncRequest.Status.RUNNING
                if request.kind == AccountPropertySyncRequest.Kind.LIVE:
                    request.snapshot_revision = state.publication_revision
                request.save(update_fields=["generation", "started_at", "status", "snapshot_revision"])
                state.save(update_fields=["generation", "active_request_id", "pending_live_request_id"])
            assert request.started_at is not None
            return AccountPropertySyncWork(
                team_id=request.binding_team_id,
                saved_query_id=saved_query_id,
                request_id=str(request.id),
                job_id=request.job_id,
                kind=cast(Literal["live", "staged"], request.kind),
                generation=request.generation,
                started_at=request.started_at.isoformat(),
            )


def begin_account_property_sync_read(*, team_id: int, saved_query_id: str) -> AccountPropertySyncRead:
    team_id = resolve_effective_team_id(team_id)
    revision = (
        AccountPropertySyncState.objects.for_team(team_id)
        .using(router.db_for_write(AccountPropertySyncState))
        .filter(saved_query_id=saved_query_id)
        .values_list("publication_revision", flat=True)
        .first()
    )
    return AccountPropertySyncRead(
        team_id=team_id,
        saved_query_id=saved_query_id,
        generation=get_account_property_sync_generation(),
        snapshot_revision=revision or 0,
    )


def begin_account_property_sync_attempt(
    *, team_id: int, saved_query_id: str, request_id: str, segment: str
) -> AccountPropertySyncRead:
    team_id = resolve_effective_team_id(team_id)
    with transaction.atomic():
        request = (
            AccountPropertySyncRequest.objects.for_team(team_id)
            .select_for_update()
            .get(id=request_id, saved_query_id=saved_query_id)
        )
        state = _get_state(team_id, saved_query_id)
        if request.status != AccountPropertySyncRequest.Status.RUNNING:
            raise AccountPropertySyncSuperseded()
        token = str(uuid4())
        request.tokens = {**request.tokens, segment: token}
        if segment == "live":
            request.snapshot_revision = state.publication_revision
        request.save(update_fields=["tokens", "snapshot_revision"])
        return AccountPropertySyncRead(
            team_id=team_id,
            saved_query_id=saved_query_id,
            generation=request.generation,
            snapshot_revision=request.snapshot_revision,
            request_id=request_id,
            token=token,
            segment=segment,
        )


@contextmanager
def guard_account_property_sync_attempt(read: AccountPropertySyncRead, *, exclusive: bool = False) -> Iterator[None]:
    using = router.db_for_write(AccountPropertySyncRequest)
    with transaction.atomic(using=using):
        if read.request_id is not None:
            # Shared locks let both segments write while blocking attempt revocation until commit.
            with connections[using].cursor() as cursor:
                cursor.execute(
                    "SELECT status, tokens FROM customer_analytics_accountpropertysyncrequest "
                    "WHERE team_id = %s AND id = %s AND saved_query_id = %s "
                    + ("FOR UPDATE" if exclusive else "FOR SHARE"),
                    [resolve_effective_team_id(read.team_id), read.request_id, read.saved_query_id],
                )
                row = cursor.fetchone()
            if row is None:
                raise AccountPropertySyncSuperseded()
            status, tokens = row
            if isinstance(tokens, str):
                tokens = json.loads(tokens)
            if status != AccountPropertySyncRequest.Status.RUNNING or tokens.get(read.segment) != read.token:
                raise AccountPropertySyncSuperseded()
        yield


def set_coordinated_source_value(
    *, read: AccountPropertySyncRead, source: CustomPropertySource, account_id: UUID, value: Any
) -> bool | None:
    if source.team_id != resolve_effective_team_id(read.team_id) or str(source.saved_query_id) != read.saved_query_id:
        raise ValueError("The property source does not belong to this sync.")
    with (
        guard_account_property_sync_attempt(read),
        guard_custom_property_value(team_id=read.team_id, account_id=account_id, definition_id=source.definition_id),
    ):
        current_source = (
            CustomPropertySource.objects.for_team(read.team_id)
            .using(router.db_for_write(CustomPropertySource))
            .select_related("definition")
            .filter(id=source.id, is_enabled=True)
            .first()
        )
        if current_source is None or get_source_mapping_key(current_source) != get_source_mapping_key(source):
            return None
        state = (
            AccountPropertySyncValueState.objects.for_team(read.team_id)
            .using(router.db_for_write(AccountPropertySyncValueState))
            .filter(account_id=account_id, definition_id=source.definition_id)
            .first()
        )
        if state is not None and state.is_direct_write and read.generation < state.generation:
            return None
        generation = read.generation
        if read.request_id is not None and read.segment != "live" and read.snapshot_revision == 0:
            generation = 0
        if state is not None and state.source_id == source.id:
            if (read.snapshot_revision, generation) < (state.snapshot_revision, state.generation):
                return None
            if generation == 0 and state.generation == 0:
                return None
        written = set_synced_custom_property_value(
            team_id=read.team_id, account_id=account_id, definition=source.definition, value=value
        )
        AccountPropertySyncValueState.objects.for_team(read.team_id).update_or_create(
            team_id=read.team_id,
            account_id=account_id,
            definition_id=source.definition_id,
            defaults={
                "source_id": source.id,
                "is_direct_write": False,
                "snapshot_revision": read.snapshot_revision,
                "generation": generation,
            },
        )
        return written


def get_account_property_snapshot_path(read: AccountPropertySyncRead, source: CustomPropertySource) -> str | None:
    with guard_account_property_sync_attempt(read):
        state = (
            AccountPropertySyncState.objects.for_team(read.team_id)
            .using(router.db_for_write(AccountPropertySyncState))
            .get(saved_query_id=read.saved_query_id)
        )
        key = f"{source.id}:{get_source_mapping_key(source)}:{read.segment}"
        path = state.snapshots.get(key)
        return path if isinstance(path, str) else None


def set_account_property_snapshot_path(
    read: AccountPropertySyncRead, source: CustomPropertySource, path: str
) -> str | None:
    with guard_account_property_sync_attempt(read):
        state = _get_state(read.team_id, read.saved_query_id)
        key = f"{source.id}:{get_source_mapping_key(source)}:{read.segment}"
        previous = state.snapshots.get(key)
        state.snapshots = {**state.snapshots, key: path}
        state.save(update_fields=["snapshots"])
        return previous if isinstance(previous, str) and previous != path else None


def finish_account_property_sync(
    *, team_id: int, saved_query_id: str, request_id: str, error: str | None = None
) -> None:
    with transaction.atomic():
        request = (
            AccountPropertySyncRequest.objects.for_team(team_id)
            .select_for_update()
            .get(id=request_id, saved_query_id=saved_query_id)
        )
        state = _get_state(team_id, saved_query_id)
        request.status = (
            AccountPropertySyncRequest.Status.FAILED if error else AccountPropertySyncRequest.Status.COMPLETED
        )
        request.error = error
        request.finished_at = timezone.now()
        request.save(update_fields=["status", "error", "finished_at"])
        if state.active_request_id == request.id:
            state.active_request_id = None
            state.save(update_fields=["active_request_id"])


def list_pending_account_property_syncs() -> list[tuple[int, str]]:
    return [
        (team_id, str(saved_query_id))
        for team_id, saved_query_id in AccountPropertySyncRequest.objects.unscoped()
        .filter(status__in=[AccountPropertySyncRequest.Status.PENDING, AccountPropertySyncRequest.Status.RUNNING])
        .order_by()
        .values_list("team_id", "saved_query_id")
        .distinct()[:1000]
    ]
