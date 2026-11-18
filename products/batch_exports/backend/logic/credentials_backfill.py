"""Link Redshift connection credentials to Integrations without changing destination config."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import field, replace
from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX
from posthog.integrations import IntegrationConflict, IntegrationManager

from products.batch_exports.backend.facade.enums import BatchExportDestinationType
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination
from products.batch_exports.backend.service import sync_batch_export

if TYPE_CHECKING:
    from uuid import UUID

    from posthog.integrations import IntegrationRecord
    from posthog.integrations.accessors import AuthAccessor

logger = structlog.get_logger(__name__)

DESTINATION_TYPES = (BatchExportDestinationType.REDSHIFT,)
NEEDS_WORK = frozenset({"needs_integration"})
UNRESOLVED_SKIPS = frozenset({"skipped_incomplete", "skipped_unreadable", "skipped_conflict"})


@frozen
class CredentialBackfillOutcome:
    destination_type: str
    outcome: str


@frozen
class _Credentials:
    accessor: AuthAccessor = field(repr=False)
    external_id: str = field(repr=False)
    config: dict[str, object] = field(repr=False)
    sensitive_config: dict[str, object] = field(repr=False)
    existing_id: int | None = None


@frozen
class _DestinationPlan:
    credentials: _Credentials | None = field(repr=False, default=None)
    outcome: str = "unchanged"
    needs_integration: bool = False


def _required(config: Mapping[str, object], *keys: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for key in keys:
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        values[key] = value
    return values


def _has_undecryptable_connection_value(config: Mapping[str, object]) -> bool:
    for key in ("host", "user", "password", "port"):
        value = config.get(key)
        if isinstance(value, str) and value.startswith(FERNET_TOKEN_PREFIX):
            return True
    return False


def _connection_credentials(export: BatchExport, config: Mapping[str, object]) -> _Credentials | None:
    values = _required(config, "host", "user", "password")
    if values is None:
        return None
    port_value = config.get("port", 5439)
    if not isinstance(port_value, (str, int)) or isinstance(port_value, bool):
        return None
    try:
        port = int(port_value)
    except ValueError:
        return None
    return _Credentials(
        accessor=IntegrationManager.aws_redshift.credentials,
        external_id=f"{export.team_id}-{values['host']}-{port}-{values['user']}",
        config={
            "host": values["host"],
            "port": port,
            "user": values["user"],
            "ssl_mode": "require",
            "ssl_root_cert": None,
        },
        sensitive_config={"password": values["password"]},
    )


def _plan(destination: BatchExportDestination, export: BatchExport) -> _DestinationPlan:
    if destination.integration_id is not None:
        return _DestinationPlan()
    if not isinstance(destination.config, dict) or _has_undecryptable_connection_value(destination.config):
        return _DestinationPlan(outcome="skipped_unreadable")
    credentials = _connection_credentials(export, destination.config)
    if credentials is None:
        return _DestinationPlan(outcome="skipped_incomplete")

    existing = credentials.accessor.find(export.team_id, external_id=credentials.external_id)
    separate = False
    if existing is not None and not _matches(existing, credentials):
        # The shared row stays untouched. This destination gets its own row, keyed by its id.
        separate = True
        credentials = replace(credentials, external_id=f"{credentials.external_id}-{destination.id}")
        existing = credentials.accessor.find(export.team_id, external_id=credentials.external_id)
        if existing is not None and not _matches(existing, credentials):
            return _DestinationPlan(outcome="skipped_conflict", needs_integration=True)
    if existing is not None:
        credentials = replace(credentials, existing_id=existing.id)

    if credentials.existing_id is not None:
        outcome = "integration_reused"
    else:
        outcome = "integration_created_separate" if separate else "integration_created"
    return _DestinationPlan(credentials=credentials, outcome=outcome, needs_integration=True)


def _matches(existing: IntegrationRecord, credentials: _Credentials) -> bool:
    return existing.config == credentials.config and existing.sensitive_config == credentials.sensitive_config


def _batches(
    team_ids: Sequence[int], destination_types: Sequence[str], batch_size: int, limit: int | None
) -> Iterator[list[BatchExportDestination]]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if limit is not None and limit < 0:
        raise ValueError("limit must be zero or greater")
    if any(kind not in DESTINATION_TYPES for kind in destination_types):
        raise ValueError("Unsupported destination type")
    exports = BatchExport.objects.filter(deleted=False)
    if team_ids:
        exports = exports.filter(team_id__in=team_ids)
    queryset = BatchExportDestination.objects.filter(
        id__in=exports.values("destination_id"), type__in=destination_types or DESTINATION_TYPES
    ).order_by("id")
    after_id: UUID | None = None
    remaining = limit
    while remaining is None or remaining > 0:
        page = queryset if after_id is None else queryset.filter(id__gt=after_id)
        page_size = batch_size if remaining is None else min(batch_size, remaining)
        batch = list(page[:page_size])
        if not batch:
            return
        after_id = batch[-1].id
        yield batch
        if remaining is not None:
            remaining -= len(batch)


def _export_for_destination(destination: BatchExportDestination, team_ids: Sequence[int]) -> BatchExport | None:
    exports = BatchExport.objects.filter(destination_id=destination.id, deleted=False)
    if team_ids:
        exports = exports.filter(team_id__in=team_ids)
    return exports.order_by("id").first()


def _sync_schedule(export: BatchExport, counts: Counter[CredentialBackfillOutcome]) -> None:
    try:
        export.refresh_from_db(
            fields=[
                field.name
                for field in BatchExport._meta.concrete_fields
                if not field.primary_key and field.name != "destination"
            ]
        )
        sync_batch_export(export, created=False)
    except Exception as error:
        counts[CredentialBackfillOutcome(destination_type=export.destination.type, outcome="schedule_sync_failed")] += 1
        logger.warning(
            "batch_export_credentials.schedule_sync_failed",
            export_id=str(export.id),
            exception_type=type(error).__name__,
        )


def _apply(destination: BatchExportDestination, export: BatchExport, plan: _DestinationPlan) -> bool:
    credentials = plan.credentials
    if credentials is None:
        return False
    if credentials.existing_id is not None:
        integration_id = credentials.existing_id
    else:
        row = credentials.accessor.create(
            export.team_id,
            external_id=credentials.external_id,
            config=credentials.config,
            sensitive_config=credentials.sensitive_config,
        )
        integration_id = row.id
    destination.integration_id = integration_id
    destination.save(update_fields=["integration_id"])
    export.destination = destination
    return True


def backfill_batch_export_credentials(
    *,
    execute: bool,
    team_ids: Sequence[int] = (),
    destination_types: Sequence[str] = (),
    limit: int | None = None,
    batch_size: int = 200,
    sync_schedules: bool = True,
    on_batch: Callable[[int], None] | None = None,
) -> Counter[CredentialBackfillOutcome]:
    counts: Counter[CredentialBackfillOutcome] = Counter()
    for batch in _batches(team_ids, destination_types, batch_size, limit):
        for destination in batch:
            try:
                if execute:
                    with transaction.atomic():
                        fresh = BatchExportDestination.objects.select_for_update().filter(id=destination.id).first()
                        if fresh is None or fresh.type not in (destination_types or DESTINATION_TYPES):
                            continue
                        export = _export_for_destination(fresh, team_ids)
                        if export is None:
                            continue
                        plan = _plan(fresh, export)
                        changed = _apply(fresh, export, plan)
                        if changed and sync_schedules:
                            transaction.on_commit(partial(_sync_schedule, export, counts))
                        destination = fresh
                else:
                    export = _export_for_destination(destination, team_ids)
                    if export is None:
                        continue
                    plan = _plan(destination, export)
                counts[CredentialBackfillOutcome(destination_type=destination.type, outcome=plan.outcome)] += 1
            except IntegrationConflict:
                counts[CredentialBackfillOutcome(destination_type=destination.type, outcome="skipped_conflict")] += 1
            except Exception as error:
                # Database exceptions can contain credentials, so never log the exception text.
                counts[CredentialBackfillOutcome(destination_type=destination.type, outcome="failed")] += 1
                logger.warning(
                    "batch_export_credentials.destination_failed",
                    destination_id=str(destination.id),
                    exception_type=type(error).__name__,
                )
        if on_batch is not None:
            on_batch(len(batch))
    return counts


def verify_batch_export_credentials(
    *, team_ids: Sequence[int] = (), destination_types: Sequence[str] = (), batch_size: int = 200
) -> Counter[CredentialBackfillOutcome]:
    counts: Counter[CredentialBackfillOutcome] = Counter()
    for batch in _batches(team_ids, destination_types, batch_size, None):
        for destination in batch:
            export = _export_for_destination(destination, team_ids)
            if export is None:
                continue
            plan = _plan(destination, export)
            if plan.needs_integration:
                counts[CredentialBackfillOutcome(destination_type=destination.type, outcome="needs_integration")] += 1
            if plan.outcome in UNRESOLVED_SKIPS:
                counts[CredentialBackfillOutcome(destination_type=destination.type, outcome=plan.outcome)] += 1
    return counts
