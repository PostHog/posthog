import csv
from datetime import datetime
from io import StringIO
from typing import TYPE_CHECKING, Any, Optional, TypeAlias
from uuid import UUID
import chdb
from django.db import models
from django.db.models import Q

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import CHQueryErrorTooManySimultaneousQueries, wrap_query_error
from posthog.exceptions_capture import capture_exception
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    FieldOrTable,
)
from posthog.hogql.database.s3_table import S3Table, build_function_call
from posthog.models.team import Team
from posthog.models.utils import (
    CreatedMetaFields,
    DeletedMetaFields,
    UpdatedMetaFields,
    UUIDModel,
    sane_repr,
)
from posthog.schema import DatabaseSerializedFieldType, HogQLQueryModifiers
from posthog.settings import TEST
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.util import (
    CLICKHOUSE_HOGQL_MAPPING,
    STR_TO_HOGQL_MAPPING,
    clean_type,
    remove_named_tuples,
)
from posthog.sync import database_sync_to_async

from .credential import DataWarehouseCredential
from .external_table_definitions import external_tables

if TYPE_CHECKING:
    pass

SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING: dict[DatabaseSerializedFieldType, str] = {
    DatabaseSerializedFieldType.INTEGER: "Int64",
    DatabaseSerializedFieldType.FLOAT: "Float64",
    DatabaseSerializedFieldType.DECIMAL: "Decimal",
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

    name = models.CharField(max_length=128)
    format = models.CharField(max_length=128, choices=TableFormat.choices)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    url_pattern = models.CharField(max_length=500)
    credential = models.ForeignKey(DataWarehouseCredential, on_delete=models.CASCADE, null=True, blank=True)

    external_data_source = models.ForeignKey("ExternalDataSource", on_delete=models.CASCADE, null=True, blank=True)

    columns = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Dict of all columns with Clickhouse type (including Nullable())",
    )

    row_count = models.IntegerField(null=True, help_text="How many rows are currently synced in this table")
    size_in_s3_mib = models.FloatField(null=True, help_text="The object size in S3 for this table in MiB")

    __repr__ = sane_repr("name")

    @property
    def name_chain(self) -> list[str]:
        return self.name.split(".")

    def soft_delete(self):
        from posthog.warehouse.models.join import DataWarehouseJoin

        for join in DataWarehouseJoin.objects.filter(
            Q(team_id=self.team.pk) & (Q(source_table_name=self.name) | Q(joining_table_name=self.name))
        ).exclude(deleted=True):
            join.soft_delete()

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

    def get_columns(
        self,
        safe_expose_ch_error: bool = True,
    ) -> DataWarehouseTableColumns:
        placeholder_context = HogQLContext(team_id=self.team.pk)
        s3_table_func = build_function_call(
            url=self.url_pattern,
            format=self.format,
            access_key=self.credential.access_key,
            access_secret=self.credential.access_secret,
            context=placeholder_context,
        )
        try:
            # chdb hangs in CI during tests
            if TEST:
                raise Exception()

            quoted_placeholders = {k: f"'{v}'" for k, v in placeholder_context.values.items()}
            # chdb doesn't support parameterized queries
            chdb_query = f"DESCRIBE TABLE (SELECT * FROM {s3_table_func} LIMIT 1)" % quoted_placeholders

            chdb_result = chdb.query(chdb_query, output_format="CSV")
            reader = csv.reader(StringIO(str(chdb_result)))
            result = [tuple(row) for row in reader]
        except Exception as chdb_error:
            capture_exception(chdb_error)

            try:
                tag_queries(team_id=self.team.pk, table_id=self.id, warehouse_query=True)

                result = sync_execute(
                    f"""DESCRIBE TABLE (
                        SELECT *
                        FROM {s3_table_func}
                        LIMIT 1
                    )""",
                    args=placeholder_context.values,
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

    def get_max_value_for_column(self, column: str) -> Any | None:
        try:
            placeholder_context = HogQLContext(team_id=self.team.pk)
            s3_table_func = build_function_call(
                url=self.url_pattern,
                format=self.format,
                access_key=self.credential.access_key,
                access_secret=self.credential.access_secret,
                context=placeholder_context,
            )

            result = sync_execute(
                f"SELECT max(`{column}`) FROM {s3_table_func}",
                args=placeholder_context.values,
            )

            return result[0][0]
        except Exception as err:
            capture_exception(err)
            return None

    def get_count(self, safe_expose_ch_error=True) -> int:
        placeholder_context = HogQLContext(team_id=self.team.pk)
        s3_table_func = build_function_call(
            url=self.url_pattern,
            format=self.format,
            access_key=self.credential.access_key,
            access_secret=self.credential.access_secret,
            context=placeholder_context,
        )
        try:
            # chdb hangs in CI during tests
            if TEST:
                raise Exception()

            quoted_placeholders = {k: f"'{v}'" for k, v in placeholder_context.values.items()}
            # chdb doesn't support parameterized queries
            chdb_query = f"SELECT count() FROM {s3_table_func}" % quoted_placeholders

            chdb_result = chdb.query(chdb_query, output_format="CSV")
            reader = csv.reader(StringIO(str(chdb_result)))
            result = [tuple(row) for row in reader]
        except Exception as chdb_error:
            capture_exception(chdb_error)

            try:
                tag_queries(team_id=self.team.pk, table_id=self.id, warehouse_query=True)

                result = sync_execute(
                    f"SELECT count() FROM {s3_table_func}",
                    args=placeholder_context.values,
                )
            except Exception as err:
                capture_exception(err)
                if safe_expose_ch_error:
                    self._safe_expose_ch_error(err)
                else:
                    raise

        return int(result[0][0])

    def get_function_call(self) -> tuple[str, HogQLContext]:
        try:
            placeholder_context = HogQLContext(team_id=self.team.pk)
            s3_table_func = build_function_call(
                url=self.url_pattern,
                format=self.format,
                access_key=self.credential.access_key,
                access_secret=self.credential.access_secret,
                context=placeholder_context,
            )

        except Exception as err:
            capture_exception(err)
            raise
        return s3_table_func, placeholder_context

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
        default_fields = external_tables.get("*", {})
        if external_table_fields is not None:
            fields = {**external_table_fields, **default_fields}
        else:
            # Hide the `_dlt` fields from tables
            if fields.get("_dlt_id") and fields.get("_dlt_load_id"):
                del fields["_dlt_id"]
                del fields["_dlt_load_id"]
                fields = {**fields, **default_fields}
            if fields.get("_ph_debug"):
                del fields["_ph_debug"]
                fields = {**fields, **default_fields}
            if fields.get(PARTITION_KEY):
                del fields[PARTITION_KEY]
                fields = {**fields, **default_fields}

        access_key: str | None = None
        access_secret: str | None = None
        if self.credential:
            access_key = self.credential.access_key
            access_secret = self.credential.access_secret

        return S3Table(
            name=self.name,
            url=self.url_pattern,
            format=self.format,
            access_key=access_key,
            access_secret=access_secret,
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

        if isinstance(err, CHQueryErrorTooManySimultaneousQueries):
            raise err

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
