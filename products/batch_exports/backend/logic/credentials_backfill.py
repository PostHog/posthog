from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import field, replace
from functools import partial
from typing import TYPE_CHECKING, cast

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX
from posthog.integrations import IntegrationConflict, IntegrationManager
from posthog.models.integration.google_cloud import InvalidGoogleTokenUriError, require_google_token_uri
from posthog.models.integration.snowflake import SnowflakeIntegration, SnowflakeIntegrationError

from products.batch_exports.backend.facade.enums import BatchExportDestinationType
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination
from products.batch_exports.backend.service import sync_batch_export

if TYPE_CHECKING:
    from uuid import UUID

    from posthog.integrations.accessors import AuthAccessor

logger = structlog.get_logger(__name__)

DESTINATION_TYPES = (
    BatchExportDestinationType.POSTGRES,
    BatchExportDestinationType.BIGQUERY,
    BatchExportDestinationType.REDSHIFT,
    BatchExportDestinationType.AWS_S3,
    BatchExportDestinationType.SNOWFLAKE,
)
NEEDS_WORK = frozenset({"needs_integration", "needs_copy_move", "needs_stale_strip"})
UNRESOLVED_SKIPS = frozenset(
    {"skipped_incomplete", "skipped_unreadable", "skipped_conflict", "copy_skipped_incomplete"}
)


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
class _CopyMove:
    key: str
    credentials_index: int


@frozen
class _DestinationPlan:
    config: dict[str, object] = field(repr=False, default_factory=dict)
    credentials: tuple[_Credentials, ...] = field(repr=False, default=())
    connection_index: int | None = None
    copy_moves: tuple[_CopyMove, ...] = ()
    outcomes: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()


def _required(config: Mapping[str, object], *keys: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for key in keys:
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        values[key] = value
    return values


def _has_undecryptable_value(value: object) -> bool:
    # The config field ignores decrypt errors and returns ciphertext for values it cannot read.
    if isinstance(value, str):
        return value.startswith(FERNET_TOKEN_PREFIX)
    if isinstance(value, dict):
        return any(_has_undecryptable_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_undecryptable_value(item) for item in value)
    return False


def _aws_credentials(config: Mapping[str, object], name: str) -> _Credentials | None:
    values = _required(config, "aws_access_key_id", "aws_secret_access_key")
    if values is None:
        return None
    return _Credentials(
        accessor=IntegrationManager.aws_s3.credentials,
        external_id=name,
        config={"name": name},
        sensitive_config=dict(values),
    )


def _connection_credentials(
    destination: BatchExportDestination, export: BatchExport, config: Mapping[str, object]
) -> _Credentials | None:
    name = f"{export.name} ({str(destination.id)[:8]})"
    if destination.type in (BatchExportDestinationType.POSTGRES, BatchExportDestinationType.REDSHIFT):
        values = _required(config, "host", "user", "password")
        if values is None:
            return None
        is_postgres = destination.type == BatchExportDestinationType.POSTGRES
        port_value = config.get("port", 5432 if is_postgres else 5439)
        if not isinstance(port_value, (str, int)) or isinstance(port_value, bool):
            return None
        try:
            port = int(port_value)
        except ValueError:
            return None
        return _Credentials(
            accessor=(
                IntegrationManager.postgresql.credentials
                if is_postgres
                else IntegrationManager.aws_redshift.credentials
            ),
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
    if destination.type == BatchExportDestinationType.BIGQUERY:
        values = _required(config, "private_key", "private_key_id", "token_uri", "client_email", "project_id")
        if values is None:
            return None
        try:
            token_uri = require_google_token_uri(values["token_uri"])
        except InvalidGoogleTokenUriError:
            return None
        return _Credentials(
            accessor=IntegrationManager.google_cloud_service_account.credentials,
            external_id=f"{values['client_email']}-{export.team_id}-key-file",
            config={"project_id": values["project_id"], "service_account_email": values["client_email"]},
            sensitive_config={
                "private_key": values["private_key"],
                "private_key_id": values["private_key_id"],
                "token_uri": token_uri,
            },
        )
    if destination.type == BatchExportDestinationType.AWS_S3:
        return _aws_credentials(config, name)
    if destination.type == BatchExportDestinationType.SNOWFLAKE:
        values = _required(config, "account", "user")
        if values is None:
            return None
        try:
            SnowflakeIntegration.validate_account(values["account"])
        except SnowflakeIntegrationError:
            return None
        authentication_type = config.get("authentication_type", "keypair" if config.get("private_key") else "password")
        if authentication_type not in ("password", "keypair"):
            return None
        secrets = _required(config, "password" if authentication_type == "password" else "private_key")
        if secrets is None:
            return None
        passphrase = config.get("private_key_passphrase")
        if authentication_type == "keypair" and isinstance(passphrase, str) and passphrase:
            secrets["private_key_passphrase"] = passphrase
        return _Credentials(
            accessor=IntegrationManager.snowflake.credentials,
            external_id=name,
            config={"name": name, **values, "authentication_type": authentication_type},
            sensitive_config=dict(secrets),
        )
    return None


def _plan(destination: BatchExportDestination, export: BatchExport) -> _DestinationPlan:
    if not isinstance(destination.config, dict) or _has_undecryptable_value(destination.config):
        return _DestinationPlan(outcomes=("skipped_unreadable",))
    config: dict[str, object] = dict(destination.config)
    credentials: list[_Credentials] = []
    outcomes: list[str] = []
    needs: list[str] = []
    connection_index: int | None = None
    if destination.integration_id is None:
        connection = _connection_credentials(destination, export, config)
        if connection is None:
            outcomes.append("skipped_incomplete")
        else:
            needs.append("needs_integration")
            connection_index = len(credentials)
            credentials.append(connection)

    if destination.integration_id is not None or connection_index is not None:
        secret_keys = BatchExportDestination.secret_fields[destination.type]
        if destination.type == BatchExportDestinationType.BIGQUERY and destination.integration_id is not None:
            # BigQuery still uses inline keys if its Integration client fails.
            secret_keys = set()
        removed = secret_keys.intersection(config)
        for key in removed:
            del config[key]
        if removed and destination.integration_id is not None:
            outcomes.append("stale_secrets_removed")
            needs.append("needs_stale_strip")

    copy_moves: list[_CopyMove] = []
    copy_credentials: list[int] = []
    copy_inputs = config.get("copy_inputs")
    if destination.type == BatchExportDestinationType.REDSHIFT and isinstance(copy_inputs, dict):
        for key in ("bucket_credentials", "authorization"):
            value = copy_inputs.get(key)
            if not isinstance(value, dict):
                continue
            suffix = f" {len(copy_credentials) + 1}" if copy_credentials else ""
            name = f"{export.name} COPY credentials ({str(destination.id)[:8]}){suffix}"
            candidate = _aws_credentials(value, name)
            if candidate is None:
                outcomes.append("copy_skipped_incomplete")
                continue
            index = next(
                (
                    index
                    for index in copy_credentials
                    if credentials[index].sensitive_config == candidate.sensitive_config
                ),
                None,
            )
            if index is None:
                index = len(credentials)
                credentials.append(candidate)
                copy_credentials.append(index)
            copy_moves.append(_CopyMove(key=key, credentials_index=index))
            if "needs_copy_move" not in needs:
                needs.append("needs_copy_move")

    for index, candidate in enumerate(credentials):
        existing = candidate.accessor.find(export.team_id, external_id=candidate.external_id)
        if existing is None:
            continue
        if existing.config != candidate.config or existing.sensitive_config != candidate.sensitive_config:
            return _DestinationPlan(outcomes=("skipped_conflict",), needs=tuple(needs))
        credentials[index] = replace(candidate, existing_id=existing.id)

    if connection_index is not None:
        outcomes.append(
            "integration_reused" if credentials[connection_index].existing_id is not None else "integration_created"
        )
    if copy_moves:
        outcomes.append("copy_credentials_moved")
    return _DestinationPlan(
        config=config,
        credentials=tuple(credentials),
        connection_index=connection_index,
        copy_moves=tuple(copy_moves),
        outcomes=tuple(outcomes) or ("unchanged",),
        needs=tuple(needs),
    )


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
        # Reload so a concurrent change such as pausing is not overwritten by a stale copy.
        export.refresh_from_db()
        sync_batch_export(export, created=False)
    except Exception as error:
        counts[CredentialBackfillOutcome(destination_type=export.destination.type, outcome="schedule_sync_failed")] += 1
        logger.warning(
            "batch_export_credentials.schedule_sync_failed",
            export_id=str(export.id),
            exception_type=type(error).__name__,
        )


def _apply(destination: BatchExportDestination, export: BatchExport, plan: _DestinationPlan) -> bool:
    if "skipped_conflict" in plan.outcomes or "skipped_unreadable" in plan.outcomes:
        return False
    integration_ids: list[int] = []
    for credentials in plan.credentials:
        if credentials.existing_id is not None:
            integration_ids.append(credentials.existing_id)
        else:
            row = credentials.accessor.create(
                export.team_id,
                external_id=credentials.external_id,
                config=credentials.config,
                sensitive_config=credentials.sensitive_config,
            )
            integration_ids.append(row.id)
    config = dict(plan.config)
    if plan.copy_moves:
        copy_inputs = dict(cast(dict[str, object], config["copy_inputs"]))
        for move in plan.copy_moves:
            copy_inputs[move.key] = integration_ids[move.credentials_index]
        config["copy_inputs"] = copy_inputs
    update_fields: list[str] = []
    if plan.connection_index is not None:
        destination.integration_id = integration_ids[plan.connection_index]
        update_fields.append("integration_id")
    if config != destination.config:
        destination.config = config
        update_fields.append("config")
    if not update_fields:
        return False
    destination.save(update_fields=update_fields)
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
                for outcome in plan.outcomes:
                    counts[CredentialBackfillOutcome(destination_type=destination.type, outcome=outcome)] += 1
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
            for outcome in plan.needs:
                counts[CredentialBackfillOutcome(destination_type=destination.type, outcome=outcome)] += 1
            for outcome in plan.outcomes:
                if outcome in UNRESOLVED_SKIPS:
                    counts[CredentialBackfillOutcome(destination_type=destination.type, outcome=outcome)] += 1
    return counts
