import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from django.conf import settings
from django.db import models

import numpy
from dateutil import parser
from django_deprecate_fields import deprecate_field
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr
from posthog.sync import database_sync_to_async
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode
from posthog.warehouse.data_load.service import (
    external_data_workflow_exists,
    pause_external_data_schedule,
    sync_external_data_job_workflow,
    unpause_external_data_schedule,
)
from posthog.warehouse.s3 import get_s3_client
from posthog.warehouse.types import IncrementalFieldType


class ExternalDataSchema(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel, DeletedMetaFields):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        PAUSED = "Paused", "Paused"
        FAILED = "Failed", "Failed"
        COMPLETED = "Completed", "Completed"
        BILLING_LIMIT_REACHED = "BillingLimitReached", "BillingLimitReached"
        BILLING_LIMIT_TOO_LOW = "BillingLimitTooLow", "BillingLimitTooLow"

    class SyncType(models.TextChoices):
        FULL_REFRESH = "full_refresh", "full_refresh"
        INCREMENTAL = "incremental", "incremental"
        APPEND = "append", "append"

    class SyncFrequency(models.TextChoices):
        DAILY = "day", "Daily"
        WEEKLY = "week", "Weekly"
        MONTHLY = "month", "Monthly"

    name = models.CharField(max_length=400)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    source = models.ForeignKey("posthog.ExternalDataSource", related_name="schemas", on_delete=models.CASCADE)
    table = models.ForeignKey("posthog.DataWarehouseTable", on_delete=models.SET_NULL, null=True, blank=True)
    should_sync = models.BooleanField(default=True)
    latest_error = models.TextField(null=True, help_text="The latest error that occurred when syncing this schema.")
    status = models.CharField(max_length=400, null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_type = models.CharField(max_length=128, choices=SyncType.choices, null=True, blank=True)
    # { "incremental_field": string, "incremental_field_type": string, "incremental_field_last_value": any, "incremental_field_earliest_value": any, "reset_pipeline": bool, "partitioning_enabled": bool, "partition_count": int, "partition_size": int, "partition_mode": str, "partitioning_keys": list[str], "chunk_size_override": int | None }
    sync_type_config = models.JSONField(
        default=dict,
        blank=True,
    )
    # Deprecated in favour of `sync_frequency_interval`
    sync_frequency = deprecate_field(
        models.CharField(max_length=128, choices=SyncFrequency.choices, default=SyncFrequency.DAILY, blank=True)
    )
    sync_frequency_interval = models.DurationField(default=timedelta(hours=6), null=True, blank=True)
    sync_time_of_day = models.TimeField(null=True, blank=True, help_text="Time of day to run the sync (UTC)")

    __repr__ = sane_repr("name")

    def folder_path(self) -> str:
        return f"team_{self.team_id}_{self.source.source_type}_{str(self.id)}".lower().replace("-", "_")

    @property
    def normalized_name(self):
        return NamingConvention().normalize_identifier(self.name)

    @property
    def is_incremental(self):
        return self.sync_type == self.SyncType.INCREMENTAL

    @property
    def is_append(self):
        return self.sync_type == self.SyncType.APPEND

    @property
    def should_use_incremental_field(self):
        return self.is_incremental or self.is_append

    @property
    def incremental_field(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field", None)

        return None

    @property
    def incremental_field_type(self) -> IncrementalFieldType | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_type", None)

        return None

    @property
    def incremental_field_last_value(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_last_value", None)

        return None

    @property
    def incremental_field_earliest_value(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_earliest_value", None)

        return None

    @property
    def reset_pipeline(self) -> bool:
        if self.sync_type_config:
            value = self.sync_type_config.get("reset_pipeline", None)
            if value is None:
                return False

            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True

        return False

    @property
    def partitioning_enabled(self) -> bool:
        if self.sync_type_config:
            value = self.sync_type_config.get("partitioning_enabled", None)
            if value is None:
                return False

            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True

        return False

    @property
    def partition_count(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_count", None)

        return None

    @property
    def partition_size(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_size", None)

        return None

    @property
    def partition_mode(self) -> PartitionMode | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_mode", None)

        return None

    @property
    def partition_format(self) -> PartitionFormat | None:
        # This key doesn't get reset on pipeline_reset and can only be set via the DB directly right now
        if self.sync_type_config:
            return self.sync_type_config.get("partition_format", None)

        return None

    @property
    def partitioning_keys(self) -> list[str] | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partitioning_keys", None)

        return None

    @property
    def chunk_size_override(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("chunk_size_override", None)

        return None

    def set_partitioning_enabled(
        self,
        partitioning_keys: list[str],
        partition_count: Optional[int],
        partition_size: Optional[int],
        partition_mode: Optional[PartitionMode],
        partition_format: Optional[PartitionFormat],
    ) -> None:
        self.sync_type_config["partitioning_enabled"] = True
        self.sync_type_config["partition_count"] = partition_count
        self.sync_type_config["partition_size"] = partition_size
        self.sync_type_config["partitioning_keys"] = partitioning_keys
        self.sync_type_config["partition_mode"] = partition_mode
        self.sync_type_config["partition_format"] = partition_format
        self.save()

    def update_sync_type_config_for_reset_pipeline(self) -> None:
        self.sync_type_config.pop("reset_pipeline", None)
        self.sync_type_config.pop("incremental_field_last_value", None)
        self.sync_type_config.pop("incremental_field_earliest_value", None)
        self.sync_type_config.pop("partitioning_enabled", None)
        self.sync_type_config.pop("partition_size", None)
        self.sync_type_config.pop("partition_count", None)
        self.sync_type_config.pop("partitioning_keys", None)
        self.sync_type_config.pop("partition_mode", None)
        self.sync_type_config.pop("backfilled_partition_format", None)
        # We don't reset partition_format
        # We don't reset chunk_size_override

        self.save()

    def update_incremental_field_value(
        self, last_value: Any, save: bool = True, type: Literal["last"] | Literal["earliest"] = "last"
    ) -> None:
        incremental_field_type = self.sync_type_config.get("incremental_field_type")

        last_value_py = last_value.item() if isinstance(last_value, numpy.generic) else last_value
        last_value_json: Any

        if last_value_py is None:
            return

        if (
            incremental_field_type == IncrementalFieldType.Integer
            or incremental_field_type == IncrementalFieldType.Numeric
        ):
            if isinstance(last_value_py, int | float):
                last_value_json = last_value_py
            elif isinstance(last_value_py, datetime):
                last_value_json = last_value_py.isoformat()
            else:
                last_value_json = int(last_value_py)
        elif (
            incremental_field_type == IncrementalFieldType.DateTime
            or incremental_field_type == IncrementalFieldType.Timestamp
        ):
            if isinstance(last_value_py, datetime):
                last_value_json = last_value_py.isoformat()
            else:
                last_value_json = str(last_value_py)
        else:
            last_value_json = str(last_value_py)

        if type == "last":
            self.sync_type_config["incremental_field_last_value"] = last_value_json
        elif type == "earliest":
            self.sync_type_config["incremental_field_earliest_value"] = last_value_json
        else:
            raise ValueError(f"Unsupported type for update_incremental_field_value: {type}")

        if save:
            self.save()

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = datetime.now()
        self.save()

    def delete_table(self):
        if self.table is not None:
            try:
                client = get_s3_client()
                client.delete(f"{settings.BUCKET_URL}/{self.folder_path()}", recursive=True)
            except Exception as e:
                capture_exception(e)

            self.table.soft_delete()
            self.table_id = None
            self.last_synced_at = None
            self.status = None
            self.save()

            self.update_sync_type_config_for_reset_pipeline()


def process_incremental_value(value: Any | None, field_type: IncrementalFieldType | None) -> Any:
    if value is None or value == "None" or field_type is None:
        return None

    if field_type == IncrementalFieldType.Integer or field_type == IncrementalFieldType.Numeric:
        return value

    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        if isinstance(value, datetime):
            return value

        return parser.parse(value)

    if field_type == IncrementalFieldType.Date:
        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        return parser.parse(value).date()

    if field_type == IncrementalFieldType.ObjectID:
        return str(value)


@database_sync_to_async
def asave_external_data_schema(schema: ExternalDataSchema) -> None:
    schema.save()


def get_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    schema = (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id=team_id, source_id=source_id, name=schema_name)
        .first()
    )
    return schema


@database_sync_to_async
def aget_schema_by_id(schema_id: str, team_id: int) -> ExternalDataSchema | None:
    return (
        ExternalDataSchema.objects.prefetch_related("source").exclude(deleted=True).get(id=schema_id, team_id=team_id)
    )


def update_should_sync(schema_id: str, team_id: int, should_sync: bool) -> ExternalDataSchema | None:
    schema = ExternalDataSchema.objects.get(id=schema_id, team_id=team_id)
    schema.should_sync = should_sync
    schema.save()

    schedule_exists = external_data_workflow_exists(schema_id)

    if schedule_exists:
        if should_sync is False:
            pause_external_data_schedule(schema_id)
        elif should_sync is True:
            unpause_external_data_schedule(schema_id)
    else:
        if should_sync is True:
            sync_external_data_job_workflow(schema, create=True)

    return schema


def get_all_schemas_for_source_id(source_id: str, team_id: int):
    return list(ExternalDataSchema.objects.exclude(deleted=True).filter(team_id=team_id, source_id=source_id).all())


def sync_old_schemas_with_new_schemas(
    new_schemas: list[str], source_id: str, team_id: int
) -> tuple[list[str], list[str]]:
    old_schemas = get_all_schemas_for_source_id(source_id=source_id, team_id=team_id)
    old_schemas_names = [schema.name for schema in old_schemas]

    schemas_to_create = [schema for schema in new_schemas if schema not in old_schemas_names]

    schemas_to_possibly_delete = [schema for schema in old_schemas_names if schema not in new_schemas]
    deleted_schemas: list[str] = []

    for schema in schemas_to_create:
        ExternalDataSchema.objects.create(name=schema, team_id=team_id, source_id=source_id, should_sync=False)

    for schema in schemas_to_possibly_delete:
        # There _could_ exist multiple schemas with the same name, there shouldn't be, but it's not impossible
        schemas_to_check = ExternalDataSchema.objects.filter(
            team_id=team_id, name=schema, source_id=source_id, deleted=False
        )
        for s in schemas_to_check:
            if s.table_id is None:
                s.soft_delete()
                deleted_schemas.append(schema)
            else:
                s.should_sync = False
                s.status = ExternalDataSchema.Status.COMPLETED
                s.save()

    return schemas_to_create, deleted_schemas


def sync_frequency_to_sync_frequency_interval(frequency: str) -> timedelta | None:
    if frequency == "never":
        return None
    if frequency == "5min":
        return timedelta(minutes=5)
    if frequency == "30min":
        return timedelta(minutes=30)
    if frequency == "1hour":
        return timedelta(hours=1)
    if frequency == "6hour":
        return timedelta(hours=6)
    if frequency == "12hour":
        return timedelta(hours=12)
    if frequency == "24hour":
        return timedelta(hours=24)
    if frequency == "7day":
        return timedelta(days=7)
    if frequency == "30day":
        return timedelta(days=30)

    raise ValueError(f"Frequency {frequency} is not supported")


def sync_frequency_interval_to_sync_frequency(sync_frequency_interval: timedelta | None) -> str | None:
    if sync_frequency_interval is None:
        return None
    if sync_frequency_interval == timedelta(minutes=5):
        return "5min"
    if sync_frequency_interval == timedelta(minutes=30):
        return "30min"
    if sync_frequency_interval == timedelta(hours=1):
        return "1hour"
    if sync_frequency_interval == timedelta(hours=6):
        return "6hour"
    if sync_frequency_interval == timedelta(hours=12):
        return "12hour"
    if sync_frequency_interval == timedelta(hours=24):
        return "24hour"
    if sync_frequency_interval == timedelta(days=7):
        return "7day"
    if sync_frequency_interval == timedelta(days=30):
        return "30day"

    raise ValueError(f"Frequency interval {sync_frequency_interval} is not supported")
