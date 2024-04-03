from typing import Dict, Optional
from django.db import models

from posthog.client import sync_execute
from posthog.errors import wrap_query_error
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)
from posthog.hogql.database.s3_table import S3Table
from posthog.models.team import Team
from posthog.models.utils import (
    CreatedMetaFields,
    DeletedMetaFields,
    UUIDModel,
    sane_repr,
)
from posthog.warehouse.models.util import remove_named_tuples
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from django.db.models import Q
from .credential import DataWarehouseCredential
from uuid import UUID
from sentry_sdk import capture_exception
from posthog.warehouse.util import database_sync_to_async
from .external_table_definitions import external_tables

CLICKHOUSE_HOGQL_MAPPING = {
    "UUID": StringDatabaseField,
    "String": StringDatabaseField,
    "DateTime64": DateTimeDatabaseField,
    "DateTime32": DateTimeDatabaseField,
    "DateTime": DateTimeDatabaseField,
    "Date": DateDatabaseField,
    "Date32": DateDatabaseField,
    "UInt8": IntegerDatabaseField,
    "UInt16": IntegerDatabaseField,
    "UInt32": IntegerDatabaseField,
    "UInt64": IntegerDatabaseField,
    "Float8": IntegerDatabaseField,
    "Float16": IntegerDatabaseField,
    "Float32": IntegerDatabaseField,
    "Float64": IntegerDatabaseField,
    "Int8": IntegerDatabaseField,
    "Int16": IntegerDatabaseField,
    "Int32": IntegerDatabaseField,
    "Int64": IntegerDatabaseField,
    "Tuple": StringJSONDatabaseField,
    "Array": StringArrayDatabaseField,
    "Map": StringJSONDatabaseField,
    "Bool": BooleanDatabaseField,
    "Decimal": IntegerDatabaseField,
}

STR_TO_HOGQL_MAPPING = {
    "BooleanDatabaseField": BooleanDatabaseField,
    "DateDatabaseField": DateDatabaseField,
    "DateTimeDatabaseField": DateTimeDatabaseField,
    "IntegerDatabaseField": IntegerDatabaseField,
    "StringArrayDatabaseField": StringArrayDatabaseField,
    "StringDatabaseField": StringDatabaseField,
    "StringJSONDatabaseField": StringJSONDatabaseField,
}

ExtractErrors = {
    "The AWS Access Key Id you provided does not exist": "The Access Key you provided does not exist",
}


class DataWarehouseTable(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    class TableFormat(models.TextChoices):
        CSV = "CSV", "CSV"
        Parquet = "Parquet", "Parquet"
        JSON = "JSONEachRow", "JSON"

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

    __repr__ = sane_repr("name")

    def table_name_without_prefix(self) -> str:
        if self.external_data_source is not None and self.external_data_source.prefix is not None:
            prefix = self.external_data_source.prefix
        else:
            prefix = ""
        return self.name[len(prefix) :]

    def get_columns(self, safe_expose_ch_error=True) -> Dict[str, str]:
        try:
            result = sync_execute(
                """DESCRIBE TABLE (
                SELECT * FROM
                    s3(%(url_pattern)s, %(access_key)s, %(access_secret)s, %(format)s)
                LIMIT 1
            )""",
                {
                    "url_pattern": self.url_pattern,
                    "access_key": self.credential.access_key,
                    "access_secret": self.credential.access_secret,
                    "format": self.format,
                },
            )
        except Exception as err:
            capture_exception(err)
            if safe_expose_ch_error:
                self._safe_expose_ch_error(err)
            else:
                raise err

        return {item[0]: item[1] for item in result}

    def hogql_definition(self) -> S3Table:
        if not self.columns:
            raise Exception("Columns must be fetched and saved to use in HogQL.")

        fields: Dict[str, FieldOrTable] = {}
        structure = []
        for column, type in self.columns.items():
            # Support for 'old' style columns
            if isinstance(type, str):
                clickhouse_type = type
            else:
                clickhouse_type = type["clickhouse"]

            if clickhouse_type.startswith("Nullable("):
                clickhouse_type = clickhouse_type.replace("Nullable(", "")[:-1]

            # TODO: remove when addressed https://github.com/ClickHouse/ClickHouse/issues/37594
            if clickhouse_type.startswith("Array("):
                clickhouse_type = remove_named_tuples(clickhouse_type)

            structure.append(f"{column} {clickhouse_type}")

            # Support for 'old' style columns
            if isinstance(type, str):
                hogql_type_str = clickhouse_type.partition("(")[0]
                hogql_type = CLICKHOUSE_HOGQL_MAPPING[hogql_type_str]
            else:
                hogql_type = STR_TO_HOGQL_MAPPING[type["hogql"]]

            fields[column] = hogql_type(name=column)

        # Replace fields with any redefined fields if they exist
        fields = external_tables.get(self.table_name_without_prefix(), fields)

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
