import re
from typing import Any, Optional

import posthoganalytics
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import FieldOrTable, SavedQuery
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDModel
from posthog.schema import HogQLQueryModifiers
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.util import (
    CLICKHOUSE_HOGQL_MAPPING,
    STR_TO_HOGQL_MAPPING,
    clean_type,
    remove_named_tuples,
)
from .credential import DataWarehouseCredential
from posthog.hogql.database.s3_table import S3Table


def validate_saved_query_name(value):
    if not re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", value):
        raise ValidationError(
            f"{value} is not a valid view name. View names can only contain letters, numbers, '_', or '$' ",
            params={"value": value},
        )

    # This doesnt protect us from naming a table the same as a warehouse table
    database = Database()
    all_keys = list(vars(database).keys())
    table_names = [key for key in all_keys if isinstance(getattr(database, key), ast.Table)]

    if value in table_names:
        raise ValidationError(
            f"{value} is not a valid view name. View names cannot overlap with PostHog table names.",
            params={"value": value},
        )


class DataWarehouseSavedQuery(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    class Status(models.TextChoices):
        """Possible states of this SavedQuery."""

        CANCELLED = "Cancelled"
        COMPLETED = "Completed"
        FAILED = "Failed"
        RUNNING = "Running"

    name = models.CharField(max_length=128, validators=[validate_saved_query_name])
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    columns = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Dict of all columns with ClickHouse type (including Nullable())",
    )
    external_tables = models.JSONField(default=list, null=True, blank=True, help_text="List of all external tables")
    query = models.JSONField(default=dict, null=True, blank=True, help_text="HogQL query")
    status = models.CharField(
        null=True, choices=Status.choices, max_length=64, help_text="The status of when this SavedQuery last ran."
    )
    last_run_at = models.DateTimeField(
        null=True,
        help_text="The timestamp of this SavedQuery's last run (if any).",
    )
    credential = models.ForeignKey(DataWarehouseCredential, on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="posthog_datawarehouse_saved_query_unique_name",
            )
        ]

    def get_columns(self) -> dict[str, dict[str, Any]]:
        from posthog.api.services.query import process_query_dict
        from posthog.hogql_queries.query_runner import ExecutionMode

        response = process_query_dict(self.team, self.query, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        result = getattr(response, "types", [])

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

    def get_clickhouse_column_type(self, column_name: str) -> Optional[str]:
        clickhouse_type = self.columns.get(column_name, None)

        if isinstance(clickhouse_type, dict) and self.columns[column_name].get("clickhouse"):
            clickhouse_type = self.columns[column_name].get("clickhouse")

            if clickhouse_type.startswith("Nullable("):
                clickhouse_type = clickhouse_type.replace("Nullable(", "")[:-1]

        return clickhouse_type

    @property
    def s3_tables(self):
        from posthog.hogql.context import HogQLContext
        from posthog.hogql.database.database import create_hogql_database
        from posthog.hogql.parser import parse_select
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

        node = resolve_types(node, context, dialect="clickhouse")
        table_collector = S3TableVisitor()
        table_collector.visit(node)

        return list(table_collector.tables)

    @property
    def url_pattern(self):
        return (
            f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/dlt/team_{self.team.pk}_model_{self.id.hex}/modeling/{self.name}"
        )

    def hogql_definition(self, modifiers: Optional[HogQLQueryModifiers] = None) -> SavedQuery:
        from posthog.warehouse.models.table import CLICKHOUSE_HOGQL_MAPPING

        columns = self.columns or {}

        fields: dict[str, FieldOrTable] = {}
        structure = []
        for column, type in columns.items():
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

            if isinstance(type, dict):
                column_invalid = not type.get("valid", True)
            else:
                column_invalid = False

            if not column_invalid or (modifiers is not None and modifiers.s3TableUseInvalidColumns):
                structure.append(f"`{column}` {clickhouse_type}")

            # Support for 'old' style columns
            if isinstance(type, str):
                hogql_type_str = clickhouse_type.partition("(")[0]
                hogql_type = CLICKHOUSE_HOGQL_MAPPING[hogql_type_str]
            else:
                hogql_type = STR_TO_HOGQL_MAPPING[type["hogql"]]

            fields[column] = hogql_type(name=column)

        if (
            self.credential is not None
            and (self.status == DataWarehouseSavedQuery.Status.COMPLETED or self.last_run_at is not None)
            and posthoganalytics.feature_enabled(
                "data-modeling",
                str(self.team.pk),
                groups={
                    "organization": str(self.team.organization_id),
                    "project": str(self.team.pk),
                },
                group_properties={
                    "organization": {
                        "id": str(self.team.organization_id),
                    },
                    "project": {
                        "id": str(self.team.pk),
                    },
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        ):
            return S3Table(
                name=self.name,
                url=self.url_pattern,
                format=DataWarehouseTable.TableFormat.Delta,
                access_key=self.credential.access_key,
                access_secret=self.credential.access_secret,
                fields=fields,
                structure=", ".join(structure),
                query=self.query["query"],
            )
        else:
            return SavedQuery(
                id=str(self.id),
                name=self.name,
                query=self.query["query"],
                fields=fields,
            )
