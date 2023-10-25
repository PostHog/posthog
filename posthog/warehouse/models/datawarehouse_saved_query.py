from posthog.models.utils import UUIDModel, CreatedMetaFields, DeletedMetaFields
from django.db import models
from posthog.models.team import Team

from posthog.hogql.database.models import SavedQuery
from posthog.hogql.database.database import Database
from typing import Dict
import re
from django.core.exceptions import ValidationError
from posthog.warehouse.models.util import remove_named_tuples


def validate_saved_query_name(value):
    if not re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", value):
        raise ValidationError(
            f"{value} is not a valid view name. View names can only contain letters, numbers, '_', or '$' ",
            params={"value": value},
        )

    if value in Database._table_names:
        raise ValidationError(
            f"{value} is not a valid view name. View names cannot overlap with PostHog table names.",
            params={"value": value},
        )


class DataWarehouseSavedQuery(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    name: models.CharField = models.CharField(max_length=128, validators=[validate_saved_query_name])
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    columns: models.JSONField = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Dict of all columns with ClickHouse type (including Nullable())",
    )
    external_tables: models.JSONField = models.JSONField(
        default=list, null=True, blank=True, help_text="List of all external tables"
    )
    query: models.JSONField = models.JSONField(default=dict, null=True, blank=True, help_text="HogQL query")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="posthog_datawarehouse_saved_query_unique_name",
            )
        ]

    def get_columns(self) -> Dict[str, str]:
        from posthog.api.query import process_query

        # TODO: catch and raise error
        response = process_query(self.team, self.query)
        types = response.get("types", {})
        return dict(types)

    @property
    def s3_tables(self):
        from posthog.hogql.parser import parse_select
        from posthog.hogql.context import HogQLContext
        from posthog.hogql.database.database import create_hogql_database
        from posthog.hogql.query import create_default_modifiers_for_team
        from posthog.hogql.resolver import resolve_types
        from posthog.models.property.util import S3TableVisitor

        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        node = parse_select(self.query["query"])
        context.database = create_hogql_database(context.team_id)

        node = resolve_types(node, context)
        table_collector = S3TableVisitor()
        table_collector.visit(node)

        return list(table_collector.tables)

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
