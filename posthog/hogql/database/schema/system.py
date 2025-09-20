from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    TableGroup,
)
from posthog.hogql.database.postgres_table import PostgresTable

cohorts: PostgresTable = PostgresTable(
    name="cohorts",
    postgres_table_name="posthog_cohort",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "filters": StringJSONDatabaseField(name="filters"),
        "groups": StringJSONDatabaseField(name="groups"),
        "query": StringJSONDatabaseField(name="query"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "last_calculation": DateTimeDatabaseField(name="last_calculation"),
        "version": IntegerDatabaseField(name="version"),
        "count": IntegerDatabaseField(name="count"),
        "_is_static": BooleanDatabaseField(name="is_static", hidden=True),
        "is_static": ExpressionField(
            name="is_static", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_static"])])
        ),
    },
)

dashboards: PostgresTable = PostgresTable(
    name="dashboards",
    postgres_table_name="posthog_dashboard",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "filters": StringJSONDatabaseField(name="filters"),
        "variables": StringJSONDatabaseField(name="variables"),
    },
)

insights: PostgresTable = PostgresTable(
    name="insights",
    postgres_table_name="posthog_dashboarditem",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "short_id": StringDatabaseField(name="short_id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
        "filters": StringJSONDatabaseField(name="filters"),
        "query": StringJSONDatabaseField(name="query"),
        "query_metadata": StringJSONDatabaseField(name="query_metadata"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "_saved": BooleanDatabaseField(name="saved", hidden=True),
        "saved": ExpressionField(name="saved", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_saved"])])),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

experiments: PostgresTable = PostgresTable(
    name="experiments",
    postgres_table_name="posthog_experiment",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
        "filters": StringJSONDatabaseField(name="filters"),
        "parameters": StringJSONDatabaseField(name="parameters"),
        "start_date": DateTimeDatabaseField(name="start_date"),
        "end_date": DateTimeDatabaseField(name="end_date"),
        "_archived": BooleanDatabaseField(name="archived", hidden=True),
        "archived": ExpressionField(
            name="archived", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_archived"])])
        ),
        "feature_flag_id": IntegerDatabaseField(name="feature_flag_id"),
    },
)

data_warehouse_sources: PostgresTable = PostgresTable(
    name="data_warehouse_sources",
    postgres_table_name="posthog_externaldatasource",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "source_type": StringDatabaseField(name="source_type"),
        "prefix": StringDatabaseField(name="prefix"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "deleted_at": DateTimeDatabaseField(name="deleted_at"),
    },
)

feature_flags: PostgresTable = PostgresTable(
    name="feature_flags",
    postgres_table_name="posthog_featureflag",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "key": StringDatabaseField(name="key"),
        "name": StringDatabaseField(name="name"),
        "filters": StringJSONDatabaseField(name="filters"),
        "rollout_percentage": IntegerDatabaseField(name="rollout_percentage"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
    },
)

groups: PostgresTable = PostgresTable(
    name="groups",
    postgres_table_name="posthog_group",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "group_key": StringDatabaseField(name="group_key"),
        "group_type_index": IntegerDatabaseField(name="group_type_index"),
        "group_properties": StringJSONDatabaseField(name="group_properties"),
        "created_at": DateTimeDatabaseField(name="created_at"),
    },
)

group_type_mappings: PostgresTable = PostgresTable(
    name="group_type_mappings",
    postgres_table_name="posthog_grouptypemapping",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "group_type": StringDatabaseField(name="group_type"),
        "name_singular": StringDatabaseField(name="name_singular"),
        "name_plural": StringDatabaseField(name="name_plural"),
    },
)

insight_variables: PostgresTable = PostgresTable(
    name="insight_variables",
    postgres_table_name="posthog_insightvariable",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "type": StringDatabaseField(name="type"),
        "code_name": StringDatabaseField(name="code_name"),
        "values": StringJSONDatabaseField(name="values"),
        "default_value": StringJSONDatabaseField(name="default_value"),
    },
)

surveys: PostgresTable = PostgresTable(
    name="surveys",
    postgres_table_name="posthog_survey",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "type": StringDatabaseField(name="type"),
        "questions": StringJSONDatabaseField(name="questions"),
        "appearance": StringJSONDatabaseField(name="appearance"),
        "start_date": DateTimeDatabaseField(name="start_date"),
        "end_date": DateTimeDatabaseField(name="end_date"),
        "created_at": DateTimeDatabaseField(name="created_at"),
    },
)

teams: PostgresTable = PostgresTable(
    name="teams",
    postgres_table_name="posthog_team",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="id"),
        "name": StringDatabaseField(name="name"),
        "timezone": StringDatabaseField(name="timezone"),
        "test_account_filters": StringJSONDatabaseField(name="test_account_filters"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

exports: PostgresTable = PostgresTable(
    name="exports",
    postgres_table_name="posthog_exportedasset",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "export_format": StringDatabaseField(name="export_format"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "export_context": StringJSONDatabaseField(name="export_context"),
    },
)


class SystemTables(TableGroup):
    tables: dict[str, Table | TableGroup] = {
        "dashboards": dashboards,
        "cohorts": cohorts,
        "insights": insights,
        "experiments": experiments,
        "exports": exports,
        "data_warehouse_sources": data_warehouse_sources,
        "feature_flags": feature_flags,
        "groups": groups,
        "group_type_mappings": group_type_mappings,
        "insight_variables": insight_variables,
        "surveys": surveys,
        "teams": teams,
    }

    def resolve_all_table_names(self) -> list[str]:
        tables = super().resolve_all_table_names()

        return [f"system.{table}" for table in tables]
