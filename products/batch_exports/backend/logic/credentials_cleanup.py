"""Remove inline credentials from batch export destination config once an Integration holds them."""

from __future__ import annotations

import json
import hashlib
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import field
from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction

import structlog
from google.oauth2 import service_account

from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX
from posthog.integrations import IntegrationConflict, IntegrationManager, IntegrationNotFound
from posthog.models.integration import GoogleCloudServiceAccountIntegration

from products.batch_exports.backend.facade.enums import BatchExportDestinationType
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination
from products.batch_exports.backend.service import sync_batch_export

if TYPE_CHECKING:
    from uuid import UUID

    from posthog.integrations import IntegrationRecord

logger = structlog.get_logger(__name__)

_S3_FIELDS = frozenset({"aws_access_key_id", "aws_secret_access_key", "endpoint_url"})

# The config keys that each destination type reads from its Integration instead of from `config`.
CREDENTIAL_FIELDS: dict[str, frozenset[str]] = {
    BatchExportDestinationType.AWS_S3: _S3_FIELDS,
    BatchExportDestinationType.S3_COMPATIBLE: _S3_FIELDS,
    BatchExportDestinationType.SNOWFLAKE: frozenset(
        {"account", "user", "authentication_type", "password", "private_key", "private_key_passphrase"}
    ),
    BatchExportDestinationType.POSTGRES: frozenset({"host", "port", "user", "password", "has_self_signed_cert"}),
    BatchExportDestinationType.REDSHIFT: frozenset({"user", "password"}),
    BatchExportDestinationType.BIGQUERY: frozenset({"private_key", "private_key_id", "token_uri", "client_email"}),
}
DESTINATION_TYPES = tuple(CREDENTIAL_FIELDS)

_INTEGRATION_KINDS: dict[str, str] = {
    BatchExportDestinationType.AWS_S3: "aws-s3",
    BatchExportDestinationType.S3_COMPATIBLE: "s3-compatible",
    BatchExportDestinationType.SNOWFLAKE: "snowflake",
    BatchExportDestinationType.POSTGRES: "postgresql",
    BatchExportDestinationType.REDSHIFT: "aws-redshift",
    BatchExportDestinationType.BIGQUERY: "google-cloud-service-account",
}

# A plain Redshift integration stores the server, so these keys are read from `config` only for
# the AWS-flavor integrations.
_REDSHIFT_SERVER_FIELDS = frozenset({"host", "port"})
_COPY_CREDENTIAL_FIELDS = ("bucket_credentials", "authorization")
_AWS_KEYS = ("aws_access_key_id", "aws_secret_access_key")

SKIPPED_NO_INTEGRATION = "skipped_no_integration"


@frozen
class CredentialCleanupOutcome:
    destination_type: str
    outcome: str


@frozen
class _AwsKeyPair:
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)

    def sensitive_config(self) -> dict[str, object]:
        return {"aws_access_key_id": self.access_key_id, "aws_secret_access_key": self.secret_access_key}


@frozen
class _CopyIntegration:
    keys: _AwsKeyPair = field(repr=False)
    external_id: str
    existing_id: int | None = None

    @property
    def key(self) -> int | str:
        """Identifies the Integration: a reused row by its id, since its external id can be empty."""
        return self.existing_id if self.existing_id is not None else self.external_id

    @property
    def outcome(self) -> str:
        return "copy_integration_reused" if self.existing_id is not None else "copy_integration_created"


@frozen
class _Plan:
    outcome: str = "unchanged"
    remove_fields: frozenset[str] = frozenset()
    copy_inputs: dict[str, object] | None = field(repr=False, default=None)
    copy_integrations: dict[str, _CopyIntegration] = field(repr=False, default_factory=dict)

    @property
    def changes(self) -> bool:
        return self.outcome in ("cleaned", "cleaned_without_integration")


class _Unreadable(Exception):
    pass


class _Conflict(Exception):
    pass


def _is_unreadable(value: object) -> bool:
    return isinstance(value, str) and value.startswith(FERNET_TOKEN_PREFIX)


def _copy_inputs(config: Mapping[str, object]) -> dict[str, object] | None:
    copy_inputs = config.get("copy_inputs")
    if isinstance(copy_inputs, str) and not _is_unreadable(copy_inputs):
        try:
            copy_inputs = json.loads(copy_inputs)
        except ValueError:
            return None
    return copy_inputs if isinstance(copy_inputs, dict) else None


def _inline_copy_keys(copy_inputs: Mapping[str, object]) -> dict[str, _AwsKeyPair]:
    """The inline AWS key pairs in Redshift `copy_inputs`, by field name."""
    pairs: dict[str, _AwsKeyPair] = {}
    for name in _COPY_CREDENTIAL_FIELDS:
        value = copy_inputs.get(name)
        if not isinstance(value, dict) or not any(key in value for key in _AWS_KEYS):
            continue
        access_key_id, secret_access_key = (value.get(key) for key in _AWS_KEYS)
        if not isinstance(access_key_id, str) or not isinstance(secret_access_key, str):
            raise _Unreadable()
        if not access_key_id.strip() or not secret_access_key.strip():
            raise _Unreadable()
        if _is_unreadable(access_key_id) or _is_unreadable(secret_access_key):
            raise _Unreadable()
        pairs[name] = _AwsKeyPair(access_key_id=access_key_id, secret_access_key=secret_access_key)
    return pairs


def _matches(row: IntegrationRecord, keys: _AwsKeyPair) -> bool:
    sensitive = row.sensitive_config or {}
    return (
        "aws_role_arn" not in (row.config or {})
        and sensitive.get("aws_access_key_id") == keys.access_key_id
        and sensitive.get("aws_secret_access_key") == keys.secret_access_key
    )


def _copy_integration(team_id: int, destination_id: UUID, keys: _AwsKeyPair) -> _CopyIntegration:
    """Find an aws-s3 Integration of the team that holds these keys, or name a new one.

    An existing Integration is never changed. When the shared name holds other keys, the
    destination gets its own Integration.
    """
    accessor = IntegrationManager.aws_s3.credentials
    for row in accessor.list(team_id):
        if _matches(row, keys):
            return _CopyIntegration(keys=keys, external_id=row.integration_id or "", existing_id=row.id)

    shared_id = f"redshift-copy-{hashlib.sha256(keys.access_key_id.encode()).hexdigest()[:16]}"
    for external_id in (shared_id, f"{shared_id}-{destination_id}"):
        if accessor.find(team_id, external_id=external_id) is None:
            return _CopyIntegration(keys=keys, external_id=external_id)
    raise _Conflict()


def _destination_integration(destination: BatchExportDestination, team_id: int) -> IntegrationRecord | str:
    """The destination's Integration, or the outcome that explains why it cannot be used."""
    assert destination.integration_id is not None
    try:
        row = IntegrationManager.kinds(*_INTEGRATION_KINDS.values(), auth_types="any").get(
            team_id, destination.integration_id
        )
    except IntegrationNotFound:
        return "skipped_integration_missing"
    if row.kind != _INTEGRATION_KINDS[destination.type]:
        return "skipped_integration_wrong_kind"
    if destination.type == BatchExportDestinationType.BIGQUERY and not _bigquery_key_is_usable(row):
        return "skipped_integration_invalid"
    return row


def _bigquery_key_is_usable(row: IntegrationRecord) -> bool:
    """Whether the worker can build credentials from the Integration's key without the inline fallback.

    The worker uses the inline keys when building credentials from a keyed Integration fails, so
    those keys must stay until the Integration's key works. Impersonated accounts have no key to check.
    """
    integration = GoogleCloudServiceAccountIntegration(row)
    if not integration.has_key():
        return True
    try:
        service_account.Credentials.from_service_account_info(integration.service_account_info)
    except Exception:
        return False
    return True


def _plan(destination: BatchExportDestination, export: BatchExport, *, include_without_integration: bool) -> _Plan:
    config = destination.config
    if not isinstance(config, dict):
        return _Plan(outcome="skipped_unreadable")

    integration: IntegrationRecord | str | None = None
    if destination.integration_id is not None:
        integration = _destination_integration(destination, export.team_id)

    fields = set(CREDENTIAL_FIELDS[destination.type])
    if (
        destination.type == BatchExportDestinationType.REDSHIFT
        and not isinstance(integration, str)
        and integration is not None
        and "host" in (integration.config or {})
    ):
        fields |= _REDSHIFT_SERVER_FIELDS
    remove_fields = frozenset(fields & config.keys())

    copy_inputs = _copy_inputs(config) if destination.type == BatchExportDestinationType.REDSHIFT else None
    if destination.type == BatchExportDestinationType.REDSHIFT and copy_inputs is None and config.get("copy_inputs"):
        # A payload that cannot be read may still hold inline keys, so it is not treated as absent.
        return _Plan(outcome="skipped_unreadable")
    try:
        copy_keys = _inline_copy_keys(copy_inputs) if copy_inputs is not None else {}
    except _Unreadable:
        return _Plan(outcome="skipped_unreadable")

    if not remove_fields and not copy_keys:
        return _Plan()
    if integration is None:
        if not include_without_integration:
            return _Plan(outcome=SKIPPED_NO_INTEGRATION)
        outcome = "cleaned_without_integration"
    elif isinstance(integration, str):
        return _Plan(outcome=integration)
    else:
        outcome = "cleaned"

    copy_integrations: dict[str, _CopyIntegration] = {}
    by_keys: dict[_AwsKeyPair, _CopyIntegration] = {}
    try:
        for name, keys in copy_keys.items():
            if keys not in by_keys:
                by_keys[keys] = _copy_integration(export.team_id, destination.id, keys)
            copy_integrations[name] = by_keys[keys]
    except _Conflict:
        return _Plan(outcome="skipped_conflict")

    return _Plan(
        outcome=outcome,
        remove_fields=remove_fields,
        copy_inputs=copy_inputs if copy_keys else None,
        copy_integrations=copy_integrations,
    )


def _copy_outcomes(plan: _Plan) -> Iterator[str]:
    seen: set[int | str] = set()
    for copy_integration in plan.copy_integrations.values():
        if copy_integration.key not in seen:
            seen.add(copy_integration.key)
            yield copy_integration.outcome


def _apply(destination: BatchExportDestination, export: BatchExport, plan: _Plan) -> None:
    config = {key: value for key, value in destination.config.items() if key not in plan.remove_fields}
    if plan.copy_inputs is not None:
        integration_ids: dict[int | str, int] = {}
        copy_inputs = dict(plan.copy_inputs)
        for name, copy_integration in plan.copy_integrations.items():
            if copy_integration.key not in integration_ids:
                if copy_integration.existing_id is not None:
                    integration_ids[copy_integration.key] = copy_integration.existing_id
                else:
                    row = IntegrationManager.aws_s3.credentials.create(
                        export.team_id,
                        external_id=copy_integration.external_id,
                        config={"name": copy_integration.external_id},
                        sensitive_config=copy_integration.keys.sensitive_config(),
                    )
                    integration_ids[copy_integration.key] = row.id
            copy_inputs[name] = integration_ids[copy_integration.key]
        config["copy_inputs"] = copy_inputs
    destination.config = config
    destination.save(update_fields=["config", "last_updated_at"])
    export.destination = destination


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


def _sync_schedule(export: BatchExport, counts: Counter[CredentialCleanupOutcome]) -> None:
    # An export with no Temporal schedule fails here too. It counts as a warning and the run goes on.
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
        counts[CredentialCleanupOutcome(destination_type=export.destination.type, outcome="schedule_sync_failed")] += 1
        logger.warning(
            "batch_export_credentials_cleanup.schedule_sync_failed",
            export_id=str(export.id),
            exception_type=type(error).__name__,
        )


def cleanup_batch_export_credentials(
    *,
    execute: bool,
    include_without_integration: bool = False,
    team_ids: Sequence[int] = (),
    destination_types: Sequence[str] = (),
    limit: int | None = None,
    batch_size: int = 200,
    on_batch: Callable[[int], None] | None = None,
) -> Counter[CredentialCleanupOutcome]:
    counts: Counter[CredentialCleanupOutcome] = Counter()
    selected_types = destination_types or DESTINATION_TYPES
    for batch in _batches(team_ids, destination_types, batch_size, limit):
        for destination in batch:
            try:
                if execute:
                    with transaction.atomic():
                        fresh = BatchExportDestination.objects.select_for_update().filter(id=destination.id).first()
                        if fresh is None or fresh.type not in selected_types:
                            continue
                        export = _export_for_destination(fresh, team_ids)
                        if export is None:
                            continue
                        plan = _plan(fresh, export, include_without_integration=include_without_integration)
                        if plan.changes:
                            _apply(fresh, export, plan)
                            transaction.on_commit(partial(_sync_schedule, export, counts))
                        destination = fresh
                else:
                    export = _export_for_destination(destination, team_ids)
                    if export is None:
                        continue
                    plan = _plan(destination, export, include_without_integration=include_without_integration)
                counts[CredentialCleanupOutcome(destination_type=destination.type, outcome=plan.outcome)] += 1
                for outcome in _copy_outcomes(plan):
                    counts[CredentialCleanupOutcome(destination_type=destination.type, outcome=outcome)] += 1
            except IntegrationConflict:
                counts[CredentialCleanupOutcome(destination_type=destination.type, outcome="skipped_conflict")] += 1
            except Exception as error:
                # Database exceptions can contain credentials, so never log the exception text.
                counts[CredentialCleanupOutcome(destination_type=destination.type, outcome="failed")] += 1
                logger.warning(
                    "batch_export_credentials_cleanup.destination_failed",
                    destination_id=str(destination.id),
                    exception_type=type(error).__name__,
                )
        if on_batch is not None:
            on_batch(len(batch))
    return counts


def verify_batch_export_credentials_cleanup(
    *,
    include_without_integration: bool = False,
    team_ids: Sequence[int] = (),
    destination_types: Sequence[str] = (),
    batch_size: int = 200,
) -> Counter[CredentialCleanupOutcome]:
    """Count the destinations that still hold inline credentials, by the reason they remain."""
    counts: Counter[CredentialCleanupOutcome] = Counter()
    for batch in _batches(team_ids, destination_types, batch_size, None):
        for destination in batch:
            export = _export_for_destination(destination, team_ids)
            if export is None:
                continue
            plan = _plan(destination, export, include_without_integration=include_without_integration)
            if plan.outcome == "unchanged":
                continue
            outcome = {
                "cleaned": "needs_cleanup",
                "cleaned_without_integration": "needs_cleanup_without_integration",
            }.get(plan.outcome, plan.outcome)
            counts[CredentialCleanupOutcome(destination_type=destination.type, outcome=outcome)] += 1
    return counts


def unresolved(counts: Mapping[CredentialCleanupOutcome, int]) -> int:
    """The verified destinations that still need work, other than the opted-out ones without an integration."""
    return sum(count for key, count in counts.items() if key.outcome != SKIPPED_NO_INTEGRATION)
