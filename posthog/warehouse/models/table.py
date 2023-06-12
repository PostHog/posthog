from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr, DeletedMetaFields
from posthog.hogql.parser import parse_expr
from posthog.errors import wrap_query_error
from django.db import models
from posthog.models.team import Team
from posthog.client import sync_execute
from .credential import DataWarehouseCredential
from posthog.clickhouse.client.escape import substitute_params
from posthog.hogql.database.models import (
    StringDatabaseField,
    IntegerDatabaseField,
    DateTimeDatabaseField,
    ExternalTable,
    LazyTable,
)
from pydantic import create_model

ClickhouseHogqlMapping = {
    "String": StringDatabaseField,
    "DateTime64": DateTimeDatabaseField,
    "DateTime32": DateTimeDatabaseField,
    "UInt32": IntegerDatabaseField,
    "UInt64": IntegerDatabaseField,
    "Int32": IntegerDatabaseField,
    "Int64": IntegerDatabaseField,
}

ExtractErrors = {
    "The AWS Access Key Id you provided does not exit": "The Access Key you provided does not exit",
}


class DataWarehouseTable(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    class TableType(models.TextChoices):
        CSV = "csv", "CSV"
        Parquet = "Parquet", "Parquet"

    name: models.CharField = models.CharField(max_length=128)
    type: models.CharField = models.CharField(max_length=128, choices=TableType.choices)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    url_pattern: models.CharField = models.CharField(max_length=500)
    credential: models.ForeignKey = models.ForeignKey(
        DataWarehouseCredential, on_delete=models.CASCADE, null=True, blank=True
    )

    columns: models.JSONField = models.JSONField(
        default=dict, null=True, blank=True, help_text="Dict of all columns with Clickhouse type (including Nullable())"
    )

    __repr__ = sane_repr("name")

    def get_columns(self):
        try:
            result = sync_execute(
                """DESCRIBE TABLE (
                SELECT * FROM
                    s3Cluster('posthog', %(url_pattern)s, %(access_key)s, %(access_secret)s, %(type)s)
                LIMIT 1
            )""",
                {
                    "url_pattern": self.url_pattern,
                    "access_key": self.credential.access_key,
                    "access_secret": self.credential.access_secret,
                    "type": self.type,
                },
            )
        except Exception as err:
            import ipdb

            ipdb.set_trace()
            self._safe_expose_ch_error(err)
        return {item[0]: item[1] for item in result}

    def hogql_definition(self) -> ExternalTable:
        if not self.columns:
            raise Exception("Columns must be fetched and saved to use in HogQL.")

        fields = {}
        for column, type in self.columns.items():
            if type.startswith("Nullable("):
                type = type.replace("Nullable(", "")[:-1]
            type = type.partition("(")[0]
            type = ClickhouseHogqlMapping[type]
            fields[column] = type(name="column")
        params = {
            "url_pattern": self.url_pattern,
            "access_key": self.credential.access_key,
            "access_secret": self.credential.access_secret,
            "type": self.type,
        }
        name = self.name

        class TableWithOverride(LazyTable):
            def hogql_table(self):
                return name

            def clickhouse_table(self):
                return name

            def lazy_select(self, requested_fields):
                return parse_expr(
                    substitute_params(
                        "s3Cluster('posthog', %(url_pattern)s, %(access_key)s, %(access_secret)s, %(type)s)", params
                    )
                )

        new_model = create_model("{}Table".format(self.name), __base__=TableWithOverride, **fields)()
        return new_model

    def _safe_expose_ch_error(self, err):
        err = wrap_query_error(err)
        for key, value in ExtractErrors.items():
            if key in err.message:
                raise Exception(value)
        raise Exception("Could not get columns")
