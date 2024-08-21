from datetime import datetime
from typing import Optional, TypeAlias
from django.db import models

from posthog.client import sync_execute
from posthog.errors import wrap_query_error
from posthog.hogql import ast
from posthog.hogql.database.models import (
    FieldOrTable,
)
from posthog.hogql.database.s3_table import S3Table, build_function_call
from posthog.models.team import Team
from posthog.models.utils import (
    CreatedMetaFields,
    DeletedMetaFields,
    UUIDModel,
    UpdatedMetaFields,
    sane_repr,
)
from posthog.schema import DatabaseSerializedFieldType, HogQLQueryModifiers
from posthog.warehouse.models.util import remove_named_tuples
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from django.db.models import Q
from .credential import DataWarehouseCredential
from uuid import UUID
from sentry_sdk import capture_exception
from posthog.warehouse.util import database_sync_to_async
from posthog.warehouse.models.util import CLICKHOUSE_HOGQL_MAPPING, clean_type, STR_TO_HOGQL_MAPPING
from .external_table_definitions import external_tables

SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING: dict[DatabaseSerializedFieldType, str] = {
    DatabaseSerializedFieldType.INTEGER: "Int64",
    DatabaseSerializedFieldType.FLOAT: "Float64",
    DatabaseSerializedFieldType.STRING: "String",
    DatabaseSerializedFieldType.DATETIME: "DateTime64",
    DatabaseSerializedFieldType.DATE: "Date",
    DatabaseSerializedFieldType.BOOLEAN: "Bool",
    DatabaseSerializedFieldType.ARRAY: "Array",
    DatabaseSerializedFieldType.JSON: "Map",
}

ExtractErrors = {
    "The AWS Access Key Id you provided does not exist": "The Access Key you provided does not exist",
    "Access Denied: while reading key:": "Access was denied when reading the provided file",
    "Could not list objects in bucket": "Access was denied to the provided bucket",
    "file is empty": "The provided file contains no data",
    "The specified key does not exist": "The provided file doesn't exist in the bucket",
    "Cannot extract table structure from CSV format file, because there are no files with provided path in S3 or all files are empty": "The provided file doesn't exist in the bucket",
    "Cannot extract table structure from Parquet format file, because there are no files with provided path in S3 or all files are empty": "The provided file doesn't exist in the bucket",
    "Cannot extract table structure from JSONEachRow format file, because there are no files with provided path in S3 or all files are empty": "The provided file doesn't exist in the bucket",
    "Bucket or key name are invalid in S3 URI": "The provided file or bucket doesn't exist",
    "S3 exception: `NoSuchBucket`, message: 'The specified bucket does not exist.'": "The provided bucket doesn't exist",
    "Either the file is corrupted or this is not a parquet file": "The provided file is not in Parquet format",
    "Rows have different amount of values": "The provided file has rows with different amount of values",
}

DataWarehouseTableColumns: TypeAlias = dict[str, dict[str, str | bool]] | dict[str, str]


class DataWarehouseTableManager(models.Manager):
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("created_by", "external_data_source")
            .prefetch_related("externaldataschema_set")
        )


class DataWarehouseTable(CreatedMetaFields, UpdatedMetaFields, UUIDModel, DeletedMetaFields):
    # loading external_data_source and credentials is easily N+1,
    # so we have a custom object manager meaning people can't forget to load them
    # this also means we _always_ have two joins whenever we load tables
    objects = DataWarehouseTableManager()

    class TableFormat(models.TextChoices):
        CSV = "CSV", "CSV"
        CSVWithNames = "CSVWithNames", "CSVWithNames"
        Parquet = "Parquet", "Parquet"
        JSON = "JSONEachRow", "JSON"
        Delta = "Delta", "Delta"
        DeltaS3Wrapper = "DeltaS3Wrapper", "DeltaS3Wrapper"

    name: models.CharField = models.CharField(max_length=128)
    format: models.CharField = models.CharField(max_length=128, choices=TableFormat.choices)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    url_pattern: models.CharField = models.CharField(max_length=500)
    credential: models.ForeignKey = models.ForeignKey(
        DataWarehouseCredential, on_delete=models.CASCADE, null=True, blank=True
    )

    external_data_source: models.ForeignKey = models.ForeignKey(
        "ExternalDataSource", on_delete=models.CASCADE, null=True, blank=True
    )

    columns: models.JSONField = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Dict of all columns with Clickhouse type (including Nullable())",
    )

    row_count: models.IntegerField = models.IntegerField(
        null=True, help_text="How many rows are currently synced in this table"
    )

    __repr__ = sane_repr("name")

    def soft_delete(self):
        from posthog.warehouse.models.join import DataWarehouseJoin

        DataWarehouseJoin.objects.filter(source_table_name=self.name).delete()
        DataWarehouseJoin.objects.filter(joining_table_name=self.name).delete()

        self.deleted = True
        self.deleted_at = datetime.now()
        self.save()

    def table_name_without_prefix(self) -> str:
        if self.external_data_source is not None and self.external_data_source.prefix is not None:
            prefix = self.external_data_source.prefix
        else:
            prefix = ""
        return self.name[len(prefix) :]

    def validate_column_type(self, column_key) -> bool:
        from posthog.hogql.query import execute_hogql_query

        if column_key not in self.columns.keys():
            raise Exception(f"Column {column_key} does not exist on table: {self.name}")

        try:
            query = ast.SelectQuery(
                select=[ast.Call(name="count", args=[ast.Field(chain=[column_key])])],
                select_from=ast.JoinExpr(table=ast.Field(chain=[self.name])),
            )

            execute_hogql_query(query, self.team, modifiers=HogQLQueryModifiers(s3TableUseInvalidColumns=True))
            return True
        except:
            return False

    def get_columns(self, safe_expose_ch_error=True) -> DataWarehouseTableColumns:
        try:
            s3_table_func = build_function_call(
                url=self.url_pattern,
                format=self.format,
                access_key=self.credential.access_key,
                access_secret=self.credential.access_secret,
            )

            result = sync_execute(
                f"""DESCRIBE TABLE (
                    SELECT *
                    FROM {s3_table_func}
                    LIMIT 1
                )"""
            )
        except Exception as err:
            capture_exception(err)
            if safe_expose_ch_error:
                self._safe_expose_ch_error(err)
            else:
                raise

        if result is None or isinstance(result, int):
            raise Exception("No columns types provided by clickhouse in get_columns")

        columns = {
            str(item[0]): {
                "hogql": CLICKHOUSE_HOGQL_MAPPING[clean_type(str(item[1]))].__name__,
                "clickhouse": item[1],
                "valid": True,
            }
            for item in result
        }

        return columns

    def get_count(self, safe_expose_ch_error=True) -> int:
        try:
            s3_table_func = build_function_call(
                url=self.url_pattern,
                format=self.format,
                access_key=self.credential.access_key,
                access_secret=self.credential.access_secret,
            )

            result = sync_execute(
                f"SELECT count() FROM {s3_table_func}",
            )
        except Exception as err:
            capture_exception(err)
            if safe_expose_ch_error:
                self._safe_expose_ch_error(err)
            else:
                raise

        return result[0][0]

    def hogql_definition(self, modifiers: Optional[HogQLQueryModifiers] = None) -> S3Table:
        columns = self.columns or {}

        fields: dict[str, FieldOrTable] = {}
        structure = []
        for column, type in columns.items():
            # Support for 'old' style columns
            if isinstance(type, str):
                clickhouse_type = type
            else:
                clickhouse_type = type["clickhouse"]

            is_nullable = False

            if clickhouse_type.startswith("Nullable("):
                clickhouse_type = clickhouse_type.replace("Nullable(", "")[:-1]
                is_nullable = True

            # TODO: remove when addressed https://github.com/ClickHouse/ClickHouse/issues/37594
            if clickhouse_type.startswith("Array("):
                clickhouse_type = remove_named_tuples(clickhouse_type)

            if isinstance(type, dict):
                column_invalid = not type.get("valid", True)
            else:
                column_invalid = False

            if not column_invalid or (modifiers is not None and modifiers.s3TableUseInvalidColumns):
                if is_nullable:
                    structure.append(f"`{column}` Nullable({clickhouse_type})")
                else:
                    structure.append(f"`{column}` {clickhouse_type}")

            # Support for 'old' style columns
            if isinstance(type, str):
                hogql_type_str = clickhouse_type.partition("(")[0]
                hogql_type = CLICKHOUSE_HOGQL_MAPPING[hogql_type_str]
            else:
                hogql_type = STR_TO_HOGQL_MAPPING[type["hogql"]]

            fields[column] = hogql_type(name=column, nullable=is_nullable)

        # Replace fields with any redefined fields if they exist
        external_table_fields = external_tables.get(self.table_name_without_prefix())
        if external_table_fields is not None:
            default_fields = external_tables.get("*", {})
            fields = {**external_table_fields, **default_fields}

        return S3Table(
            name=self.name,
            url=self.url_pattern,
            format=self.format,
            access_key=self.credential.access_key,
            access_secret=self.credential.access_secret,
            fields=fields,
            structure=", ".join(structure),
        )

    def get_clickhouse_column_type(self, column_name: str) -> Optional[str]:
        clickhouse_type = self.columns.get(column_name, None)

        if isinstance(clickhouse_type, dict) and self.columns[column_name].get("clickhouse"):
            clickhouse_type = self.columns[column_name].get("clickhouse")

            if clickhouse_type.startswith("Nullable("):
                clickhouse_type = clickhouse_type.replace("Nullable(", "")[:-1]

        return clickhouse_type

    def _safe_expose_ch_error(self, err):
        err = wrap_query_error(err)
        for key, value in ExtractErrors.items():
            if key in err.message:
                raise Exception(value)
        raise Exception("Could not get columns")


@database_sync_to_async
def get_table_by_url_pattern_and_source(url_pattern: str, source_id: UUID, team_id: int) -> DataWarehouseTable:
    return DataWarehouseTable.objects.filter(Q(deleted=False) | Q(deleted__isnull=True)).get(
        team_id=team_id, external_data_source_id=source_id, url_pattern=url_pattern
    )


@database_sync_to_async
def get_table_by_schema_id(schema_id: str, team_id: int):
    return ExternalDataSchema.objects.get(id=schema_id, team_id=team_id).table


@database_sync_to_async
def acreate_datawarehousetable(**kwargs):
    return DataWarehouseTable.objects.create(**kwargs)


@database_sync_to_async
def asave_datawarehousetable(table: DataWarehouseTable) -> None:
    table.save()
