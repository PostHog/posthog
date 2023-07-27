from posthog.models.utils import UUIDModel, CreatedMetaFields, DeletedMetaFields
from django.db import models
from posthog.models.team import Team

from posthog.hogql.database.models import View
from typing import Dict
import re


class DatawarehouseSavedQuery(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    name: models.CharField = models.CharField(max_length=128, unique=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    columns: models.JSONField = models.JSONField(
        default=dict, null=True, blank=True, help_text="Dict of all columns with Clickhouse type (including Nullable())"
    )
    query: models.JSONField = models.JSONField(default=dict, null=True, blank=True, help_text="HogQL query")

    def get_columns(self) -> Dict[str, str]:
        from posthog.api.query import process_query

        # TODO: catch and raise error
        response = process_query(self.team, self.query)
        types = response.get("types", {})
        return dict(types)

    def hogql_definition(self) -> View:
        from posthog.warehouse.models.table import ClickhouseHogqlMapping

        if not self.columns:
            raise Exception("Columns must be fetched and saved to use in HogQL.")

        fields = {}
        for column, type in self.columns.items():
            if type.startswith("Nullable("):
                type = type.replace("Nullable(", "")[:-1]

            # TODO: remove when addressed https://github.com/ClickHouse/ClickHouse/issues/37594
            if type.startswith("Array("):
                type = self.remove_named_tuples(type)

            type = type.partition("(")[0]
            type = ClickhouseHogqlMapping[type]
            fields[column] = type(name=column)

        return View(
            name=self.name,
            query=self.query["query"],
            fields=fields,
        )

    # repeated from table.py
    def remove_named_tuples(self, type):
        from posthog.warehouse.models.table import ClickhouseHogqlMapping

        """Remove named tuples from query"""
        tokenified_type = re.split(r"(\W)", type)
        filtered_tokens = [
            token
            for token in tokenified_type
            if token == "Nullable"
            or (len(token) == 1 and not token.isalnum())
            or token in ClickhouseHogqlMapping.keys()
        ]
        return "".join(filtered_tokens)
