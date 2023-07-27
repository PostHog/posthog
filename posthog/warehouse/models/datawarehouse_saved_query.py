from posthog.models.utils import UUIDModel, CreatedMetaFields, DeletedMetaFields
from django.db import models
from posthog.models.team import Team

from posthog.hogql.database.models import SavedQuery
from posthog.hogql.database.database import Database
from typing import Dict

from django.core.exceptions import ValidationError
from posthog.warehouse.models.util import remove_named_tuples


def validate_database_name(value):
    if value in Database._table_names:
        raise ValidationError(
            f"{value} is not a valid view name. View names cannot overlap with PostHog table names.",
            params={"value": value},
        )


class DatawarehouseSavedQuery(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    name: models.CharField = models.CharField(max_length=128, validators=[validate_database_name])
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    columns: models.JSONField = models.JSONField(
        default=dict, null=True, blank=True, help_text="Dict of all columns with Clickhouse type (including Nullable())"
    )
    query: models.JSONField = models.JSONField(default=dict, null=True, blank=True, help_text="HogQL query")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["name"], name="posthog_datawarehouse_saved_query_unique_name")]

    def get_columns(self) -> Dict[str, str]:
        from posthog.api.query import process_query

        # TODO: catch and raise error
        response = process_query(self.team, self.query)
        types = response.get("types", {})
        return dict(types)

    def hogql_definition(self) -> SavedQuery:
        from posthog.warehouse.models.table import CLICKHOUSE_HOGQL_MAPPING

        if not self.columns:
            raise Exception("Columns must be fetched and saved to use in HogQL.")

        fields = {}
        for column, type in self.columns.items():
            if type.startswith("Nullable("):
                type = type.replace("Nullable(", "")[:-1]

            # TODO: remove when addressed https://github.com/ClickHouse/ClickHouse/issues/37594
            if type.startswith("Array("):
                type = remove_named_tuples(type)

            type = type.partition("(")[0]
            type = CLICKHOUSE_HOGQL_MAPPING[type]
            fields[column] = type(name=column)

        return SavedQuery(
            name=self.name,
            query=self.query["query"],
            fields=fields,
        )
