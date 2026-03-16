from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    TableNode,
)
from posthog.hogql.database.postgres_table import PostgresTable


class IngestionWarningsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False, hidden=True),
        "source": StringDatabaseField(name="source", nullable=False),
        "type": StringDatabaseField(name="type", nullable=False),
        "details": StringDatabaseField(name="details", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "ingestion_warnings"

    def to_printed_hogql(self):
        return "ingestion_warnings"


cohort_calculation_history: PostgresTable = PostgresTable(
    name="cohort_calculation_history",
    postgres_table_name="posthog_cohortcalculationhistory",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "cohort_id": IntegerDatabaseField(name="cohort_id"),
        "count": IntegerDatabaseField(name="count"),
        "started_at": DateTimeDatabaseField(name="started_at"),
        "finished_at": DateTimeDatabaseField(name="finished_at"),
        "error_code": StringDatabaseField(name="error_code"),
    },
)

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
    access_scope="dashboard",
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
    access_scope="insight",
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
    access_scope="experiment",
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
    access_scope="external_data_source",
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

data_modeling_views: PostgresTable = PostgresTable(
    name="data_modeling_views",
    postgres_table_name="posthog_datawarehousesavedquery",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "status": StringDatabaseField(name="status"),
        "columns": StringJSONDatabaseField(name="columns"),
        "query": StringJSONDatabaseField(name="query"),
        "last_run_at": DateTimeDatabaseField(name="last_run_at"),
        "_is_materialized": BooleanDatabaseField(name="is_materialized", hidden=True),
        "is_materialized": ExpressionField(
            name="is_materialized", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_materialized"])])
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "deleted_at": DateTimeDatabaseField(name="deleted_at"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

data_warehouse_tables: PostgresTable = PostgresTable(
    name="data_warehouse_tables",
    postgres_table_name="posthog_datawarehousetable",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "columns": StringJSONDatabaseField(name="columns"),
        "row_count": IntegerDatabaseField(name="row_count"),
        "external_data_source_id": StringDatabaseField(name="external_data_source_id"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "deleted_at": DateTimeDatabaseField(name="deleted_at"),
    },
)

source_schemas: PostgresTable = PostgresTable(
    name="source_schemas",
    postgres_table_name="posthog_externaldataschema",
    access_scope="external_data_source",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "source_id": StringDatabaseField(name="source_id"),
        "table_id": StringDatabaseField(name="table_id"),
        "should_sync": BooleanDatabaseField(name="should_sync"),
        "status": StringDatabaseField(name="status"),
        "sync_type": StringDatabaseField(name="sync_type"),
        "last_synced_at": DateTimeDatabaseField(name="last_synced_at"),
        "latest_error": StringDatabaseField(name="latest_error"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "deleted_at": DateTimeDatabaseField(name="deleted_at"),
    },
)

source_sync_jobs: PostgresTable = PostgresTable(
    name="source_sync_jobs",
    postgres_table_name="posthog_externaldatajob",
    access_scope="external_data_source",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "pipeline_id": StringDatabaseField(name="pipeline_id"),
        "schema_id": StringDatabaseField(name="schema_id"),
        "status": StringDatabaseField(name="status"),
        "rows_synced": IntegerDatabaseField(name="rows_synced"),
        "billable": BooleanDatabaseField(name="billable"),
        "latest_error": StringDatabaseField(name="latest_error"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "finished_at": DateTimeDatabaseField(name="finished_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

feature_flags: PostgresTable = PostgresTable(
    name="feature_flags",
    postgres_table_name="posthog_featureflag",
    access_scope="feature_flag",
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
    access_scope="survey",
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

actions: PostgresTable = PostgresTable(
    name="actions",
    postgres_table_name="posthog_action",
    access_scope="action",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
        "steps_json": StringJSONDatabaseField(name="steps_json"),
    },
)

annotations: PostgresTable = PostgresTable(
    name="annotations",
    postgres_table_name="posthog_annotation",
    access_scope="annotation",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "content": StringDatabaseField(name="content", nullable=True),
        "scope": StringDatabaseField(name="scope"),
        "creation_type": StringDatabaseField(name="creation_type"),
        "date_marker": DateTimeDatabaseField(name="date_marker", nullable=True),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "dashboard_item_id": IntegerDatabaseField(name="dashboard_item_id", nullable=True),
        "dashboard_id": IntegerDatabaseField(name="dashboard_id", nullable=True),
        "created_by_id": IntegerDatabaseField(name="created_by_id", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

hog_flows: PostgresTable = PostgresTable(
    name="hog_flows",
    postgres_table_name="posthog_hogflow",
    access_scope="hog_flow",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
        "status": StringDatabaseField(name="status"),
        "version": IntegerDatabaseField(name="version"),
        "exit_condition": StringDatabaseField(name="exit_condition"),
        "trigger": StringJSONDatabaseField(name="trigger"),
        "edges": StringJSONDatabaseField(name="edges"),
        "actions": StringJSONDatabaseField(name="actions"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

hog_functions: PostgresTable = PostgresTable(
    name="hog_functions",
    postgres_table_name="posthog_hogfunction",
    access_scope="hog_function",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
        "type": StringDatabaseField(name="type"),
        "_enabled": BooleanDatabaseField(name="enabled", hidden=True),
        "enabled": ExpressionField(name="enabled", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_enabled"])])),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "icon_url": StringDatabaseField(name="icon_url"),
        "template_id": StringDatabaseField(name="template_id"),
        "execution_order": IntegerDatabaseField(name="execution_order"),
        "inputs_schema": StringJSONDatabaseField(name="inputs_schema"),
        "filters": StringJSONDatabaseField(name="filters"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

notebooks: PostgresTable = PostgresTable(
    name="notebooks",
    postgres_table_name="posthog_notebook",
    access_scope="notebook",
    fields={
        "id": StringDatabaseField(name="id"),
        "short_id": StringDatabaseField(name="short_id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "title": StringDatabaseField(name="title"),
        "content": StringJSONDatabaseField(name="content"),
        "text_content": StringDatabaseField(name="text_content"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "visibility": StringDatabaseField(name="visibility"),
        "version": IntegerDatabaseField(name="version"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "last_modified_at": DateTimeDatabaseField(name="last_modified_at"),
    },
)

data_modeling_jobs: PostgresTable = PostgresTable(
    name="data_modeling_jobs",
    postgres_table_name="posthog_datamodelingjob",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "data_modeling_view_id": StringDatabaseField(name="saved_query_id"),
        "status": StringDatabaseField(name="status"),
        "rows_materialized": IntegerDatabaseField(name="rows_materialized"),
        "rows_expected": IntegerDatabaseField(name="rows_expected"),
        "error": StringDatabaseField(name="error"),
        "storage_delta_mib": FloatDatabaseField(name="storage_delta_mib"),
        "last_run_at": DateTimeDatabaseField(name="last_run_at"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

error_tracking_issues: PostgresTable = PostgresTable(
    name="error_tracking_issues",
    postgres_table_name="posthog_errortrackingissue",
    access_scope="error_tracking",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "status": StringDatabaseField(name="status"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
    },
)

error_tracking_issue_assignments: PostgresTable = PostgresTable(
    name="error_tracking_issue_assignments",
    postgres_table_name="posthog_errortrackingissueassignment",
    access_scope="error_tracking",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "issue_id": StringDatabaseField(name="issue_id"),
        "user_id": IntegerDatabaseField(name="user_id"),
        "role_id": StringDatabaseField(name="role_id"),
    },
)

error_tracking_issue_fingerprints: PostgresTable = PostgresTable(
    name="error_tracking_issue_fingerprints",
    postgres_table_name="posthog_errortrackingissuefingerprintv2",
    access_scope="error_tracking",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "issue_id": StringDatabaseField(name="issue_id"),
        "fingerprint": StringDatabaseField(name="fingerprint"),
        "first_seen": DateTimeDatabaseField(name="first_seen"),
    },
)


class SystemTables(TableNode):
    name: str = "system"
    children: dict[str, TableNode] = {
        "actions": TableNode(name="actions", table=actions),
        "annotations": TableNode(name="annotations", table=annotations),
        "cohort_calculation_history": TableNode(name="cohort_calculation_history", table=cohort_calculation_history),
        "cohorts": TableNode(name="cohorts", table=cohorts),
        "dashboards": TableNode(name="dashboards", table=dashboards),
        "data_modeling_jobs": TableNode(name="data_modeling_jobs", table=data_modeling_jobs),
        "data_modeling_views": TableNode(name="data_modeling_views", table=data_modeling_views),
        "data_warehouse_sources": TableNode(name="data_warehouse_sources", table=data_warehouse_sources),
        "data_warehouse_tables": TableNode(name="data_warehouse_tables", table=data_warehouse_tables),
        "error_tracking_issue_assignments": TableNode(
            name="error_tracking_issue_assignments", table=error_tracking_issue_assignments
        ),
        "error_tracking_issue_fingerprints": TableNode(
            name="error_tracking_issue_fingerprints", table=error_tracking_issue_fingerprints
        ),
        "error_tracking_issues": TableNode(name="error_tracking_issues", table=error_tracking_issues),
        "experiments": TableNode(name="experiments", table=experiments),
        "exports": TableNode(name="exports", table=exports),
        "feature_flags": TableNode(name="feature_flags", table=feature_flags),
        "groups": TableNode(name="groups", table=groups),
        "group_type_mappings": TableNode(name="group_type_mappings", table=group_type_mappings),
        "hog_flows": TableNode(name="hog_flows", table=hog_flows),
        "hog_functions": TableNode(name="hog_functions", table=hog_functions),
        "ingestion_warnings": TableNode(name="ingestion_warnings", table=IngestionWarningsTable()),
        "insight_variables": TableNode(name="insight_variables", table=insight_variables),
        "insights": TableNode(name="insights", table=insights),
        "notebooks": TableNode(name="notebooks", table=notebooks),
        "source_schemas": TableNode(name="source_schemas", table=source_schemas),
        "source_sync_jobs": TableNode(name="source_sync_jobs", table=source_sync_jobs),
        "surveys": TableNode(name="surveys", table=surveys),
        "teams": TableNode(name="teams", table=teams),
    }
