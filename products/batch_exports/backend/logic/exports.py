"""Scheduled batch exports: read, create and change them, check what they save, pause or unpause them.

The facade reaches this module through a call-time import, because it imports the service layer,
the Temporal client and the HogQL parser, none of which may load on the ``django.setup()`` path.
"""

import typing
import contextlib
import dataclasses
from uuid import UUID

from django.db import transaction

from posthog.hogql import ast

from posthog.integrations import IntegrationKind, IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.models import Team, User
from posthog.models.integration import (
    AzureBlobIntegration,
    AzureBlobIntegrationError,
    DatabricksIntegration,
    DatabricksIntegrationError,
    SnowflakeIntegration,
    SnowflakeIntegrationError,
)
from posthog.security.url_validation import (
    INVALID_HOST_MESSAGE,
    UNREACHABLE_HOST_MESSAGE,
    ShapeError,
    validate_external_host,
)
from posthog.temporal.common.client import sync_connect

from products.batch_exports.backend import service
from products.batch_exports.backend.custom_events_schema import build_events_query_schema
from products.batch_exports.backend.facade import contracts
from products.batch_exports.backend.facade.enums import (
    AZURE_BLOB_SUPPORTED_COMPRESSIONS,
    BATCH_EXPORT_INTEGRATION_KINDS,
    OBJECT_STORAGE_DESTINATIONS,
    S3_FAMILY_TYPES,
    S3_SUPPORTED_COMPRESSIONS,
    BatchExportDestinationType,
    BatchExportModel,
)
from products.batch_exports.backend.hogql_source import load_hogql_modifiers, validate_hogql_query_for_batch_export
from products.batch_exports.backend.logic.runs import to_run_detail
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination, BatchExportSource

# S3-family destinations that may authenticate via an Integration, mapped to
# the linked integration's kind. Adding a future S3-family destination (e.g. a
# first-class GCS-via-S3 type) is a one-line addition here.
_S3_DESTINATION_TO_INTEGRATION_KIND: dict[str, IntegrationKind] = {
    BatchExportDestinationType.AWS_S3: IntegrationKind.AWS_S3,
    BatchExportDestinationType.S3_COMPATIBLE: IntegrationKind.S3_COMPATIBLE,
}

# The only URLs an HTTP destination may send to, as SSRF protection.
_ALLOWED_HTTP_DESTINATION_URLS = ("https://us.i.posthog.com/batch/", "https://eu.i.posthog.com/batch/")


def load_batch_export(team_id: int, export_id: UUID, *related: str) -> BatchExport:
    """Load a live export of the team, joining only the ``related`` fields the caller reads."""
    batch_exports = BatchExport.objects.exclude(deleted=True)
    # `select_related()` with no fields joins every non-null foreign key, so only call it with some.
    if related:
        batch_exports = batch_exports.select_related(*related)
    try:
        return batch_exports.get(id=export_id, team_id=team_id)
    except BatchExport.DoesNotExist as e:
        raise contracts.BatchExportNotFoundError() from e


def _get_integration(team_id: int, integration_id: int | None) -> IntegrationRecord | None:
    if integration_id is None:
        return None
    try:
        return IntegrationManager.kinds(*BATCH_EXPORT_INTEGRATION_KINDS).get(team_id, integration_id)
    except IntegrationNotFound as e:
        raise contracts.InvalidBatchExportDestinationError(
            "The integration for this destination no longer exists. Choose another integration and try again."
        ) from e


def _recursive_dict_merge(
    old: typing.Mapping[str, typing.Any],
    new: typing.Mapping[str, typing.Any],
) -> dict[str, typing.Any]:
    """Merge two dictionaries, and recursively merge any dictionaries in them."""
    merged = {**old, **new}

    for key, value in merged.items():
        if not isinstance(value, dict):
            continue

        # Recurse only when both sides are dicts: a dict replacing a scalar (e.g. inline
        # credentials replacing an IAM role or an integration id) is an overwrite, not a merge.
        old_value = old.get(key)
        new_value = new.get(key)
        merged[key] = _recursive_dict_merge(
            old_value if isinstance(old_value, dict) else {},
            new_value if isinstance(new_value, dict) else {},
        )

    return merged


def _writes_compressed_parquet(config: dict[str, typing.Any]) -> bool:
    """Whether a config produces Parquet file names that carry a compression codec."""
    return config.get("file_format") == "Parquet" and config.get("compression") is not None


def _uses_legacy_parquet_extension(destination_type: str, stored_config: dict[str, typing.Any]) -> bool:
    """Whether an export's stored config already writes the codec into its Parquet file names.

    Reads through `coerce_config_to_declared_types`, because `EncryptedJSONField` stringifies
    scalars on write and the string "False" is truthy.
    """
    coerced = service.coerce_config_to_declared_types(destination_type, stored_config)
    stored = coerced.get("legacy_parquet_extension")
    if stored is None:
        # export was created before the `legacy_parquet_extension` field was added
        # so will use the legacy extension if it writes compressed Parquet files
        return _writes_compressed_parquet(coerced)
    return bool(stored)


def _set_default_parquet_extension(destination_type: str, config: dict[str, typing.Any]) -> None:
    """Opt a newly created destination into the standard `.parquet` extension.

    The workflow input dataclasses default this to `True`, so that an export whose Temporal
    schedule predates the field keeps the same file extension as before in order to maintain
    compatibility.
    """
    if destination_type in OBJECT_STORAGE_DESTINATIONS:
        config.setdefault("legacy_parquet_extension", False)


def _pin_existing_parquet_extension(destination_type: str, stored_config: dict[str, typing.Any]) -> None:
    """Record what an export's file names already look like, before a patch can change its format.

    An export that predates this setting has no value for it, and a missing value reads as the
    legacy naming. That is correct only for an export that already writes names carrying a codec,
    which means Parquet with a compression codec set. An export on JSON Lines, or on Parquet with
    no compression, has no such names to keep, so moving it to compressed Parquet has to produce
    `.parquet` rather than `.parquet.zst`.

    Takes the config as stored, before the incoming patch merges into it, so the value reflects
    what the export has been running rather than what it is moving to. An explicit value in the
    patch still wins, because the merge applies afterwards.
    """
    if destination_type not in OBJECT_STORAGE_DESTINATIONS:
        return

    stored_config.setdefault("legacy_parquet_extension", _writes_compressed_parquet(stored_config))


def _coerce_integration_id(value: typing.Any) -> int | None:
    """Return the integration id encoded in a Redshift COPY credential value, if any.

    `BatchExportDestination.config` is an `EncryptedJSONField`, which stringifies scalar
    leaves on the decrypt round trip, so an id may arrive as an int or a numeric string.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _check_file_format(merged_config: dict[str, typing.Any], supported_compressions: dict[str, list[str]]) -> None:
    # JSONLines is the default file format for S3 exports for legacy reasons
    file_format = merged_config.get("file_format", "JSONLines")
    supported_file_formats = supported_compressions.keys()
    if file_format not in supported_file_formats:
        raise contracts.InvalidBatchExportDestinationError(
            f"File format {file_format} is not supported. Supported file formats are {list(supported_file_formats)}"
        )
    compression = merged_config.get("compression", None)
    if compression and compression not in supported_compressions[file_format]:
        raise contracts.InvalidBatchExportDestinationError(
            f"Compression {compression} is not supported for file format {file_format}. Supported compressions are {supported_compressions[file_format]}"
        )


def _check_redshift_copy_inputs(
    team_id: int,
    instance: BatchExport | None,
    merged_config: dict[str, typing.Any],
    existing_config: dict[str, typing.Any],
) -> None:
    copy_inputs = merged_config.get("copy_inputs", {})
    if not copy_inputs:
        raise contracts.InvalidBatchExportDestinationError("Missing required inputs for 'COPY'")

    required_inputs = {"s3_bucket", "region_name", "authorization", "bucket_credentials"}
    if required_inputs - copy_inputs.keys():
        raise contracts.InvalidBatchExportDestinationError("Missing required input for 'COPY'")

    credential_keys = {"aws_access_key_id", "aws_secret_access_key"}

    bucket_credentials = copy_inputs["bucket_credentials"]
    bucket_integration_id = _coerce_integration_id(bucket_credentials)
    authorization = copy_inputs.get("authorization")
    authorization_integration_id = _coerce_integration_id(authorization)

    existing_copy_inputs = existing_config.get("copy_inputs") or {}

    for field_name, copy_integration_id in (
        ("bucket_credentials", bucket_integration_id),
        ("authorization", authorization_integration_id),
    ):
        # Sticky like the top-level integration: COPY credentials that reference an
        # integration cannot drop back to inline values.
        # TODO: remove this guard once integrations are mandatory for Redshift and
        # inline credentials are gone.
        if (
            instance is not None
            and copy_integration_id is None
            and _coerce_integration_id(existing_copy_inputs.get(field_name)) is not None
        ):
            raise contracts.InvalidBatchExportDestinationError(
                f"Cannot switch '{field_name}' from an integration to inline credentials. "
                "Send a different integration ID to swap, or omit the field to keep the current one."
            )
        if copy_integration_id is None:
            continue
        # These ids live inside `config` rather than the team-scoped `integration`
        # field, so team ownership must be checked here.
        if copy_integration_id not in IntegrationManager.aws_s3.credentials.get_many(team_id, [copy_integration_id]):
            raise contracts.InvalidBatchExportDestinationError(
                f"'{field_name}' does not reference an AWS S3 integration of this project."
            )

    if bucket_integration_id is None and (
        not isinstance(bucket_credentials, dict) or credential_keys - bucket_credentials.keys()
    ):
        raise contracts.InvalidBatchExportDestinationError("Missing required bucket credentials for 'COPY'")

    if authorization_integration_id is None:
        if isinstance(authorization, dict):
            if credential_keys - authorization.keys():
                raise contracts.InvalidBatchExportDestinationError("Missing required credentials for 'COPY'")
        elif isinstance(authorization, str):
            if not authorization.strip():
                raise contracts.InvalidBatchExportDestinationError("Missing required IAM role for 'COPY'")
        else:
            raise contracts.InvalidBatchExportDestinationError(
                "Authorization for 'COPY' must be an IAM role ARN, AWS credentials, or an integration ID."
            )


def validate_destination(
    team_id: int,
    *,
    export_id: UUID | None,
    destination_type: str,
    config: typing.Mapping[str, typing.Any],
    integration_change: contracts.IntegrationChange | None,
) -> None:
    """Check that a destination can be saved, for a new export or as a change to ``export_id``.

    ``integration_change`` is None when the request left the integration out, which keeps the
    export's existing integration. An explicit null sends ``IntegrationChange(integration_id=None)``.

    Raises:
        contracts.InvalidBatchExportDestinationError: If the destination fails a check. The
            message says which one.
        contracts.BatchExportNotFoundError: If ``export_id`` names no export of the team.
    """
    # The caller's copy of the export has its secrets stripped, and the Redshift COPY check reads the
    # stored inline credentials, so the export is read again here.
    # TODO: once inline credentials are gone, take the existing destination from the caller instead.
    instance = (
        load_batch_export(team_id, export_id, "destination", "destination__integration")
        if export_id is not None
        else None
    )
    existing_config: dict[str, typing.Any] = instance.destination.config if instance is not None else {}

    if instance is not None and destination_type != instance.destination.type:
        raise contracts.InvalidBatchExportDestinationError(
            f"Cannot change destination type from '{instance.destination.type}' to '{destination_type}'. "
            "Delete this batch export and create a new one with the new destination type."
        )

    # This setting is used for grandfathered exports that used the legacy Parquet file extension,
    # and is a one-way migration; once exports use the new `.parquet` extension it is not
    # possible to go back to using the legacy extension.
    if config.get("legacy_parquet_extension") is True and not _uses_legacy_parquet_extension(
        destination_type, existing_config
    ):
        raise contracts.InvalidBatchExportDestinationError(
            "'legacy_parquet_extension' can only stay on for an export that already writes the "
            "compression codec into its Parquet file names. It cannot be turned on for a new "
            "export, or turned back on once an export moved to the standard '.parquet' extension."
        )

    merged_config = _recursive_dict_merge(existing_config, config)

    # `requested_integration` is the integration the request sent: None when it sent none, or sent
    # an explicit null. `kept_integration` is the one the export has after the change: a PATCH may
    # send config alone, which keeps the export's existing integration. An explicit
    # `integration: null` is a removal, and is rejected below.
    requested_integration: IntegrationRecord | None
    kept_integration: IntegrationRecord | None
    if integration_change is None:
        requested_integration = None
        kept_integration = instance.destination.integration if instance is not None else None
    else:
        if (
            instance is not None
            and integration_change.integration_id is not None
            and instance.destination.integration_id == integration_change.integration_id
        ):
            # A PATCH usually sends the export's current integration again, which is already loaded.
            requested_integration = instance.destination.integration
        else:
            requested_integration = _get_integration(team_id, integration_change.integration_id)
        kept_integration = requested_integration

    # SSRF protection for HTTP batch exports
    if destination_type == BatchExportDestinationType.HTTP:
        url = merged_config.get("url")
        if url and url not in _ALLOWED_HTTP_DESTINATION_URLS:
            raise contracts.InvalidBatchExportDestinationError(f"Invalid destination URL: {url}")

    if destination_type == BatchExportDestinationType.SNOWFLAKE:
        integration = kept_integration
        if integration is None:
            raise contracts.InvalidBatchExportDestinationError("Integration is required for Snowflake batch exports")

        # Also rejects an integration missing its account, user or authentication type, so a
        # half-built one fails here rather than on the export's first run.
        try:
            SnowflakeIntegration(integration)
        except SnowflakeIntegrationError as e:
            raise contracts.InvalidBatchExportDestinationError(str(e))

    if destination_type in S3_FAMILY_TYPES:
        integration = kept_integration
        if integration is None:
            raise contracts.InvalidBatchExportDestinationError(
                f"Integration is required for {destination_type} batch exports"
            )

        # Credentials and the provider endpoint are not declared on the input dataclasses, so
        # `validate_destination_config` already rejects them as unknown fields.

        # we already validate the required inputs in `validate_destination_config`
        # so here we just ensure that the inputs are not empty
        required_non_empty_inputs = ["bucket_name", "region", "prefix"]

        empty_inputs = []

        for required_input in required_non_empty_inputs:
            value = config.get(required_input)
            if value is not None and isinstance(value, str) and value.strip() == "":
                empty_inputs.append(required_input)

        if empty_inputs:
            raise contracts.InvalidBatchExportDestinationError(f"The following inputs are empty: {empty_inputs}")

        # The integration must match the destination kind. (Team ownership is already enforced
        # by the team-scoped `integration` field, which can only resolve integrations belonging
        # to the request's team.)
        if integration.kind != _S3_DESTINATION_TO_INTEGRATION_KIND[destination_type]:
            raise contracts.InvalidBatchExportDestinationError(
                f"Integration provided is not an AWS S3 integration (got kind='{integration.kind}')"
            )

        _check_file_format(merged_config, S3_SUPPORTED_COMPRESSIONS)

    if destination_type == BatchExportDestinationType.DATABRICKS:
        # validate the Integration is valid (this is mandatory for Databricks batch exports)
        if requested_integration is None:
            raise contracts.InvalidBatchExportDestinationError("Integration is required for Databricks batch exports")
        if requested_integration.kind != IntegrationKind.DATABRICKS:
            raise contracts.InvalidBatchExportDestinationError("Integration is not a Databricks integration.")
        # try instantiate the integration to check if it's valid
        try:
            DatabricksIntegration(requested_integration)
        except DatabricksIntegrationError as e:
            raise contracts.InvalidBatchExportDestinationError(str(e))

    if destination_type == BatchExportDestinationType.POSTGRES:
        # New Postgres exports must use an Integration for credentials. Exports created before
        # integrations existed keep their inline credentials, so only require it on create
        # (`instance is None`); existing inline-credential exports stay valid when edited.
        if requested_integration is None and instance is None:
            raise contracts.InvalidBatchExportDestinationError("Integration is required for Postgres batch exports")
        if requested_integration is not None and requested_integration.kind != IntegrationKind.POSTGRESQL:
            raise contracts.InvalidBatchExportDestinationError("Integration is not a PostgreSQL integration.")

    if destination_type == BatchExportDestinationType.BIGQUERY:
        if requested_integration is None:
            raise contracts.InvalidBatchExportDestinationError("Integration is required for BigQuery batch exports")
        if requested_integration.kind != IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT:
            raise contracts.InvalidBatchExportDestinationError(
                "Integration is not a Google Cloud service account integration."
            )

    if destination_type == BatchExportDestinationType.AZURE_BLOB:
        # validate the Integration is valid (this is mandatory for Azure Blob batch exports)
        if requested_integration is None:
            raise contracts.InvalidBatchExportDestinationError("Integration is required for Azure Blob batch exports")
        if requested_integration.kind != IntegrationKind.AZURE_BLOB:
            raise contracts.InvalidBatchExportDestinationError("Integration is not an Azure Blob integration.")
        # try instantiate the integration to check if it's valid
        try:
            AzureBlobIntegration(requested_integration)
        except AzureBlobIntegrationError as e:
            raise contracts.InvalidBatchExportDestinationError(str(e))

        _check_file_format(merged_config, AZURE_BLOB_SUPPORTED_COMPRESSIONS)

    if destination_type == BatchExportDestinationType.REDSHIFT:
        # Sticky integration: an export that uses one cannot drop back to inline credentials.
        # TODO: remove this guard once inline credentials are gone.
        if instance is not None and instance.destination.integration is not None and requested_integration is None:
            raise contracts.InvalidBatchExportDestinationError(
                "Cannot remove the integration from a Redshift batch export that uses one. "
                "Re-send its `integration` to keep it (or a different one to swap)."
            )

        # New Redshift exports must use an Integration for credentials. Exports created before
        # integrations existed keep their inline credentials, so only require it on create
        # (`instance is None`); existing inline-credential exports stay valid when edited.
        if requested_integration is None and instance is None:
            raise contracts.InvalidBatchExportDestinationError("Integration is required for Redshift batch exports")

        if requested_integration is not None:
            # (Team ownership is already enforced by the team-scoped `integration` field.)
            if requested_integration.kind != IntegrationKind.AWS_REDSHIFT:
                raise contracts.InvalidBatchExportDestinationError("Integration is not a Redshift integration.")

            # Only plain Redshift integrations store a host; AWS-flavor ones obtain
            # temporary credentials for a cluster endpoint that stays in the export config.
            if "host" not in requested_integration.config and not merged_config.get("host"):
                raise contracts.InvalidBatchExportDestinationError(
                    "A 'host' is required when using an AWS Redshift integration: "
                    "set it to the cluster or workgroup endpoint."
                )

        if merged_config.get("mode") == "COPY":
            _check_redshift_copy_inputs(team_id, instance, merged_config, existing_config)

    if destination_type in (
        BatchExportDestinationType.POSTGRES,
        BatchExportDestinationType.REDSHIFT,
    ):
        # PostgreSQL-server integrations (Postgres, plain Redshift) keep the host in the
        # linked Integration; AWS Redshift integrations and inline configs keep it in
        # `config`. Prefer the Integration's host when it has one so we don't skip
        # SSRF validation (and don't `KeyError` on a `config` that has no `host`).
        host = requested_integration.config.get("host") if requested_integration is not None else None
        if host is None:
            host = merged_config.get("host")

        if host is not None:
            try:
                validate_external_host(host)
            except ShapeError:
                raise contracts.InvalidBatchExportDestinationError(INVALID_HOST_MESSAGE)
            except ValueError:
                raise contracts.InvalidBatchExportDestinationError(UNREACHABLE_HOST_MESSAGE)


def prepare_new_destination_config(
    destination_type: str, config: typing.Mapping[str, typing.Any]
) -> dict[str, typing.Any]:
    """Return the config a new destination saves, with the defaults a new export opts into."""
    prepared = dict(config)
    _set_default_parquet_extension(destination_type, prepared)
    return prepared


def merge_destination_config(
    destination_type: str, stored_config: typing.Mapping[str, typing.Any], patch: typing.Mapping[str, typing.Any]
) -> dict[str, typing.Any]:
    """Return the config an export saves after a patch merges into its stored config."""
    pinned = dict(stored_config)
    _pin_existing_parquet_extension(destination_type, pinned)
    return _recursive_dict_merge(pinned, patch)


def get_destination_test_config(team_id: int, export_id: UUID) -> dict[str, typing.Any]:
    """Return an export's stored destination config, limited to the fields its workflow inputs declare.

    Raises:
        contracts.BatchExportNotFoundError: If the team has no such live export.
    """
    batch_export = load_batch_export(team_id, export_id, "destination")

    # Remove any additional fields from stored configuration
    _, workflow_inputs = service.DESTINATION_WORKFLOWS[batch_export.destination.type]
    workflow_fields = {field.name for field in dataclasses.fields(workflow_inputs)}
    return {k: v for k, v in batch_export.destination.config.items() if k in workflow_fields}


def delete_batch_export(team_id: int, export_id: UUID) -> None:
    """Delete an export: pause it, cancel its running work, then drop its Temporal schedule.

    Raises:
        contracts.BatchExportNotFoundError: If the team has no such live export.
    """
    # The activity log reads the destination when the delete saves the export.
    batch_export = load_batch_export(team_id, export_id, "destination")
    service.delete_batch_export(batch_export)


@contextlib.contextmanager
def _map_schedule_errors() -> typing.Iterator[None]:
    try:
        yield
    except service.BatchExportIdError as e:
        raise contracts.BatchExportNotFoundError() from e
    except service.BatchExportServiceRPCError as e:
        raise contracts.BatchExportScheduleError() from e


def pause_batch_export(team_id: int, export_id: UUID, *, note: str) -> None:
    """Pause an export's Temporal schedule.

    Raises:
        contracts.BatchExportNotFoundError: If the team has no such export.
        contracts.BatchExportScheduleError: If Temporal rejects the change.
    """
    with _map_schedule_errors():
        service.pause_batch_export(sync_connect(), str(export_id), note=note, team_id=team_id)


def unpause_batch_export(team_id: int, export_id: UUID, *, note: str, backfill: bool) -> None:
    """Unpause an export's Temporal schedule, and with ``backfill``, backfill the runs missed while paused.

    Raises:
        contracts.BatchExportNotFoundError: If the team has no such export.
        contracts.BatchExportScheduleError: If Temporal rejects the change.
    """
    with _map_schedule_errors():
        service.unpause_batch_export(sync_connect(), str(export_id), note=note, backfill=backfill, team_id=team_id)


def _get_user(user_id: int) -> User:
    return User.objects.get(id=user_id)


def validate_hogql_query(
    team_id: int, user_id: int, hogql_query: str, hogql_modifiers: dict[str, typing.Any] | None
) -> tuple[str, ...]:
    """Check that a HogQL query can power a batch export, with the user's permissions, and return its output columns.

    Raises:
        contracts.UnsupportedHogQLQueryError: If the query cannot power a batch export.
    """
    parsed = validate_hogql_query_for_batch_export(
        hogql_query,
        Team.objects.get(id=team_id),
        user=_get_user(user_id),
        modifiers=load_hogql_modifiers(hogql_modifiers),
    )
    # NOTE: Should be populated after a successful preparation
    assert isinstance(parsed.type, (ast.SelectQueryType, ast.SelectSetQueryType))
    return tuple(parsed.type.columns)


def organization_has_custom_events_schema_exports(organization_id: UUID) -> bool:
    """Whether a team of the organization has an events model export with a stored query schema.

    Only those organizations may still send a HogQL query with the events model.
    """
    return BatchExport.objects.filter(schema__isnull=False, team__organization_id=organization_id).exists()


# TODO: remove this and `BatchExportDestination.secret_fields` once inline credentials are gone.
def _remove_secret_fields(destination_type: str, config: dict[str, typing.Any]) -> dict[str, typing.Any]:
    target = {}

    for k, v in config.items():
        if k in BatchExportDestination.secret_fields[destination_type]:
            continue
        elif isinstance(v, dict):
            target[k] = _remove_secret_fields(destination_type, v)
        else:
            target[k] = v

    return target


def _to_configuration(batch_export: BatchExport, *, include_latest_runs: bool) -> contracts.BatchExportConfiguration:
    destination = batch_export.destination
    return contracts.BatchExportConfiguration(
        id=batch_export.id,
        team_id=batch_export.team_id,
        name=batch_export.name,
        model=batch_export.model,
        destination=contracts.BatchExportDestinationConfiguration(
            type=destination.type,
            config=service.coerce_config_to_declared_types(
                destination.type, _remove_secret_fields(destination.type, destination.config)
            ),
            integration=destination.integration_id,
        ),
        interval=batch_export.interval,
        paused=batch_export.paused,
        created_at=batch_export.created_at,
        last_updated_at=batch_export.last_updated_at,
        last_paused_at=batch_export.last_paused_at,
        start_at=batch_export.start_at,
        end_at=batch_export.end_at,
        latest_runs=tuple(to_run_detail(run) for run in batch_export.latest_runs) if include_latest_runs else (),
        hogql_query=batch_export.hogql_query,
        hogql_modifiers=batch_export.hogql_modifiers,
        primary_key=tuple(batch_export.primary_key) if batch_export.primary_key is not None else None,
        version_key=tuple(batch_export.version_key) if batch_export.version_key is not None else None,
        incremental_mode=batch_export.incremental_mode,
        schema=batch_export.schema,
        filters=batch_export.filters,
        timezone=batch_export.timezone,
        offset_day=batch_export.offset_day,
        offset_hour=batch_export.offset_hour,
    )


def get_batch_export(team_id: int, export_id: UUID, *, include_latest_runs: bool) -> contracts.BatchExportConfiguration:
    batch_export = load_batch_export(team_id, export_id, "destination", "source")
    return _to_configuration(batch_export, include_latest_runs=include_latest_runs)


def list_batch_exports(
    team_id: int, *, offset: int, limit: int
) -> tuple[list[contracts.BatchExportConfiguration], int]:
    batch_exports = (
        BatchExport.objects.exclude(deleted=True)
        .filter(team_id=team_id)
        # Workflows exports are backfills that the Workflows product starts, so the list leaves them out.
        .exclude(destination__type=BatchExportDestinationType.WORKFLOWS)
        .order_by("-created_at", "-id")
        .select_related("destination", "source")
    )
    page = batch_exports[offset : offset + limit]
    return [_to_configuration(batch_export, include_latest_runs=True) for batch_export in page], batch_exports.count()


def schedule_and_save(batch_export: BatchExport) -> None:
    """Create the Temporal schedule of a new export, then save the export, its destination and its source."""
    # Schedule first, then the rows. This trades one failure for the other: a failed save leaves
    # an orphaned schedule, where the reverse order would leave a row pointing at no schedule.
    # Neither failure is compensated.
    service.sync_batch_export(batch_export, created=True)

    with transaction.atomic():
        batch_export.destination.save()
        if batch_export.source is not None:
            batch_export.source.save()
        batch_export.save()


def create_batch_export(
    team_id: int, user_id: int, new: contracts.NewBatchExport
) -> contracts.BatchExportConfiguration:
    """Create a scheduled batch export, then its Temporal schedule, then save it."""
    user = _get_user(user_id)

    source = None
    schema = None
    if new.model == BatchExportModel.HOGQL:
        source = BatchExportSource(
            team_id=team_id,
            hogql_query=new.hogql_query,
            hogql_modifiers=new.hogql_modifiers,
            primary_key=list(new.primary_key) if new.primary_key is not None else None,
            version_key=list(new.version_key) if new.version_key is not None else None,
        )
    elif new.hogql_query is not None:
        # TODO: Migrate batch exports using a HogQL query to HogQL model.
        schema = build_events_query_schema(team_id, user, new.hogql_query)

    destination = BatchExportDestination(
        type=new.destination.type,
        config=prepare_new_destination_config(new.destination.type, new.destination.config),
        integration_id=new.destination.integration_id,
    )

    batch_export = BatchExport(
        team_id=team_id,
        destination=destination,
        source=source,
        last_modified_by=user,
        name=new.name,
        model=new.model,
        interval=new.interval,
        paused=new.paused,
        last_paused_at=new.last_paused_at,
        start_at=new.start_at,
        end_at=new.end_at,
        filters=new.filters,
        timezone=new.timezone,
        interval_offset=new.interval_offset,
        incremental_mode=new.incremental_mode,
        schema=schema,
    )

    schedule_and_save(batch_export)

    # A new export has no runs yet.
    return _to_configuration(batch_export, include_latest_runs=False)


# The fields of `BatchExportUpdate` that set the model field of the same name.
_UPDATABLE_FIELDS = (
    "name",
    "interval",
    "paused",
    "last_paused_at",
    "start_at",
    "end_at",
    "filters",
    "timezone",
    "interval_offset",
    "incremental_mode",
)
_SOURCE_FIELDS = ("hogql_query", "hogql_modifiers", "primary_key", "version_key")


def update_batch_export(
    team_id: int, export_id: UUID, user_id: int, update: contracts.BatchExportUpdate
) -> contracts.BatchExportConfiguration:
    """Change a scheduled batch export, and sync its Temporal schedule in the same transaction."""
    user = _get_user(user_id)
    batch_export = load_batch_export(team_id, export_id, "destination", "source")

    events_query_changed = batch_export.model != BatchExportModel.HOGQL and "hogql_query" in update.changed
    schema = (
        build_events_query_schema(team_id, user, update.hogql_query)
        if events_query_changed and update.hogql_query is not None
        else None
    )

    with transaction.atomic():
        if update.destination is not None:
            destination = batch_export.destination
            # Type changes are rejected by `validate_destination`, so the incoming `type`
            # (if any) always equals the existing type by the time we get here.
            destination.config = merge_destination_config(
                destination.type, destination.config, update.destination.config
            )
            if update.destination.integration is not None:
                destination.integration_id = update.destination.integration.integration_id

        if batch_export.model == BatchExportModel.HOGQL:
            if any(name in update.changed for name in _SOURCE_FIELDS):
                source = batch_export.source or BatchExportSource(team_id=batch_export.team_id)

                for name in _SOURCE_FIELDS:
                    if name in update.changed:
                        value = getattr(update, name)
                        # The model stores the key columns as lists, the contract as tuples.
                        setattr(source, name, list(value) if isinstance(value, tuple) else value)

                source.save()
                batch_export.source = source

        elif events_query_changed:
            batch_export.schema = schema

        batch_export.destination.save()

        for name in _UPDATABLE_FIELDS:
            if name in update.changed:
                setattr(batch_export, name, getattr(update, name))
        batch_export.last_modified_by = user
        batch_export.save()

        service.sync_batch_export(batch_export, created=False)

    return _to_configuration(batch_export, include_latest_runs=True)
