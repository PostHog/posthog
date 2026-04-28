from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    TableNode,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.parser import parse_expr


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


batch_export_backfills: PostgresTable = PostgresTable(
    name="batch_export_backfills",
    postgres_table_name="posthog_batchexportbackfill",
    access_scope="batch_export",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "batch_export_id": StringDatabaseField(name="batch_export_id"),
        "start_at": DateTimeDatabaseField(name="start_at", nullable=True),
        "end_at": DateTimeDatabaseField(name="end_at", nullable=True),
        "status": StringDatabaseField(name="status"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "finished_at": DateTimeDatabaseField(name="finished_at", nullable=True),
        "last_updated_at": DateTimeDatabaseField(name="last_updated_at"),
        "total_records_count": IntegerDatabaseField(name="total_records_count", nullable=True),
    },
)

batch_exports: PostgresTable = PostgresTable(
    name="batch_exports",
    postgres_table_name="posthog_batchexport",
    access_scope="batch_export",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "model": StringDatabaseField(name="model", nullable=True),
        "interval": StringDatabaseField(name="interval"),
        "_paused": BooleanDatabaseField(name="paused", hidden=True),
        "paused": ExpressionField(name="paused", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_paused"])])),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "destination_id": StringDatabaseField(name="destination_id"),
        "timezone": StringDatabaseField(name="timezone"),
        "interval_offset": IntegerDatabaseField(name="interval_offset", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "last_updated_at": DateTimeDatabaseField(name="last_updated_at"),
        "last_paused_at": DateTimeDatabaseField(name="last_paused_at", nullable=True),
        "start_at": DateTimeDatabaseField(name="start_at", nullable=True),
        "end_at": DateTimeDatabaseField(name="end_at", nullable=True),
    },
)

alerts: PostgresTable = PostgresTable(
    name="alerts",
    postgres_table_name="posthog_alertconfiguration",
    access_scope="alert",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "insight_id": IntegerDatabaseField(name="insight_id"),
        "enabled": BooleanDatabaseField(name="enabled"),
        "state": StringDatabaseField(name="state"),
        "calculation_interval": StringDatabaseField(name="calculation_interval"),
        "condition": StringJSONDatabaseField(name="condition"),
        "config": StringJSONDatabaseField(name="config"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "last_notified_at": DateTimeDatabaseField(name="last_notified_at"),
        "last_checked_at": DateTimeDatabaseField(name="last_checked_at"),
        "next_check_at": DateTimeDatabaseField(name="next_check_at"),
        "snoozed_until": DateTimeDatabaseField(name="snoozed_until"),
        "skip_weekend": BooleanDatabaseField(name="skip_weekend"),
        "schedule_restriction": StringJSONDatabaseField(name="schedule_restriction"),
    },
)

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
        "_favorited": BooleanDatabaseField(name="favorited", hidden=True),
        "favorited": ExpressionField(
            name="favorited", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_favorited"])])
        ),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "created_by_id": IntegerDatabaseField(name="created_by_id", nullable=True),
        "last_modified_at": DateTimeDatabaseField(name="last_modified_at"),
        "last_modified_by_id": IntegerDatabaseField(name="last_modified_by_id", nullable=True),
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

endpoint_versions: PostgresTable = PostgresTable(
    name="data_modeling_endpoint_versions",
    postgres_table_name="endpoints_endpointversion",
    access_scope="endpoint",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "endpoint_id": StringDatabaseField(name="endpoint_id"),
        "version": IntegerDatabaseField(name="version"),
        "description": StringDatabaseField(name="description"),
        "query": StringJSONDatabaseField(name="query"),
        "data_freshness_seconds": IntegerDatabaseField(name="data_freshness_seconds"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "_is_active": BooleanDatabaseField(name="is_active", hidden=True),
        "is_active": ExpressionField(
            name="is_active", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_active"])])
        ),
        "columns": StringJSONDatabaseField(name="columns"),
    },
)

endpoints: PostgresTable = PostgresTable(
    name="data_modeling_endpoints",
    postgres_table_name="endpoints_endpoint",
    predicates=[parse_expr("deleted != true")],
    access_scope="endpoint",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "_is_active": BooleanDatabaseField(name="is_active", hidden=True),
        "is_active": ExpressionField(
            name="is_active", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_active"])])
        ),
        "current_version": IntegerDatabaseField(name="current_version"),
        "derived_from_insight": StringDatabaseField(name="derived_from_insight"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
        "last_executed_at": DateTimeDatabaseField(name="last_executed_at"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
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

integrations: PostgresTable = PostgresTable(
    name="integrations",
    postgres_table_name="posthog_integration",
    access_scope="integration",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "kind": StringDatabaseField(name="kind"),
        "integration_id": StringDatabaseField(name="integration_id"),
        "config": StringJSONDatabaseField(name="config"),
        "errors": StringDatabaseField(name="errors"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "created_by_id": IntegerDatabaseField(name="created_by_id"),
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

session_recording_playlists: PostgresTable = PostgresTable(
    name="session_recording_playlists",
    postgres_table_name="posthog_sessionrecordingplaylist",
    access_scope="session_recording_playlist",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "short_id": StringDatabaseField(name="short_id"),
        "name": StringDatabaseField(name="name"),
        "derived_name": StringDatabaseField(name="derived_name"),
        "description": StringDatabaseField(name="description"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "_pinned": BooleanDatabaseField(name="pinned", hidden=True),
        "pinned": ExpressionField(name="pinned", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_pinned"])])),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "filters": StringJSONDatabaseField(name="filters"),
        "type": StringDatabaseField(name="type"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "created_by_id": IntegerDatabaseField(name="created_by_id"),
        "last_modified_at": DateTimeDatabaseField(name="last_modified_at"),
        "last_modified_by_id": IntegerDatabaseField(name="last_modified_by_id"),
    },
)

session_recordings: PostgresTable = PostgresTable(
    name="session_recordings",
    postgres_table_name="posthog_sessionrecording",
    access_scope="session_recording",
    fields={
        "id": StringDatabaseField(name="id"),
        "session_id": StringDatabaseField(name="session_id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "duration": IntegerDatabaseField(name="duration"),
        "active_seconds": IntegerDatabaseField(name="active_seconds"),
        "inactive_seconds": IntegerDatabaseField(name="inactive_seconds"),
        "start_time": DateTimeDatabaseField(name="start_time"),
        "end_time": DateTimeDatabaseField(name="end_time"),
        "click_count": IntegerDatabaseField(name="click_count"),
        "keypress_count": IntegerDatabaseField(name="keypress_count"),
        "mouse_activity_count": IntegerDatabaseField(name="mouse_activity_count"),
        "console_log_count": IntegerDatabaseField(name="console_log_count"),
        "console_warn_count": IntegerDatabaseField(name="console_warn_count"),
        "console_error_count": IntegerDatabaseField(name="console_error_count"),
        "start_url": StringDatabaseField(name="start_url"),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "retention_period_days": IntegerDatabaseField(name="retention_period_days"),
        "storage_version": StringDatabaseField(name="storage_version"),
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

activity_logs: PostgresTable = PostgresTable(
    name="activity_logs",
    postgres_table_name="posthog_activitylog",
    access_scope="activity_log",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "activity": StringDatabaseField(name="activity"),
        "item_id": StringDatabaseField(name="item_id"),
        "scope": StringDatabaseField(name="scope"),
        "detail": StringJSONDatabaseField(name="detail"),
        "created_at": DateTimeDatabaseField(name="created_at"),
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

error_tracking_assignment_rules: PostgresTable = PostgresTable(
    name="error_tracking_assignment_rules",
    postgres_table_name="posthog_errortrackingassignmentrule",
    access_scope="error_tracking",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "user_id": IntegerDatabaseField(name="user_id", nullable=True),
        "role_id": StringDatabaseField(name="role_id", nullable=True),
        "order_key": IntegerDatabaseField(name="order_key"),
        "filters": StringJSONDatabaseField(name="filters"),
        "bytecode": StringJSONDatabaseField(name="bytecode"),
        "disabled_data": StringJSONDatabaseField(name="disabled_data", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

error_tracking_suppression_rules: PostgresTable = PostgresTable(
    name="error_tracking_suppression_rules",
    postgres_table_name="posthog_errortrackingsuppressionrule",
    access_scope="error_tracking",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "order_key": IntegerDatabaseField(name="order_key"),
        "sampling_rate": FloatDatabaseField(name="sampling_rate"),
        "filters": StringJSONDatabaseField(name="filters"),
        "bytecode": StringJSONDatabaseField(name="bytecode", nullable=True),
        "disabled_data": StringJSONDatabaseField(name="disabled_data", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

error_tracking_releases: PostgresTable = PostgresTable(
    name="error_tracking_releases",
    postgres_table_name="posthog_errortrackingrelease",
    access_scope="error_tracking",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "hash_id": StringDatabaseField(name="hash_id"),
        "version": StringDatabaseField(name="version"),
        "project": StringDatabaseField(name="project"),
        "metadata": StringJSONDatabaseField(name="metadata", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at"),
    },
)

logs_views: PostgresTable = PostgresTable(
    name="logs_views",
    postgres_table_name="logs_logsview",
    access_scope="logs",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "short_id": StringDatabaseField(name="short_id"),
        "name": StringDatabaseField(name="name"),
        "filters": StringJSONDatabaseField(name="filters"),
        "_pinned": BooleanDatabaseField(name="pinned", hidden=True),
        "pinned": ExpressionField(name="pinned", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_pinned"])])),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

logs_alerts: PostgresTable = PostgresTable(
    name="logs_alerts",
    postgres_table_name="logs_logsalertconfiguration",
    access_scope="logs",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name"),
        "_enabled": BooleanDatabaseField(name="enabled", hidden=True),
        "enabled": ExpressionField(name="enabled", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_enabled"])])),
        "filters": StringJSONDatabaseField(name="filters"),
        "threshold_count": IntegerDatabaseField(name="threshold_count"),
        "threshold_operator": StringDatabaseField(name="threshold_operator"),
        "window_minutes": IntegerDatabaseField(name="window_minutes"),
        "check_interval_minutes": IntegerDatabaseField(name="check_interval_minutes"),
        "state": StringDatabaseField(name="state"),
        "evaluation_periods": IntegerDatabaseField(name="evaluation_periods"),
        "datapoints_to_alarm": IntegerDatabaseField(name="datapoints_to_alarm"),
        "cooldown_minutes": IntegerDatabaseField(name="cooldown_minutes"),
        "snooze_until": DateTimeDatabaseField(name="snooze_until", nullable=True),
        "next_check_at": DateTimeDatabaseField(name="next_check_at", nullable=True),
        "last_notified_at": DateTimeDatabaseField(name="last_notified_at", nullable=True),
        "last_checked_at": DateTimeDatabaseField(name="last_checked_at", nullable=True),
        "consecutive_failures": IntegerDatabaseField(name="consecutive_failures"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

support_tickets: PostgresTable = PostgresTable(
    name="support_tickets",
    postgres_table_name="posthog_conversations_ticket",
    access_scope="ticket",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "ticket_number": IntegerDatabaseField(name="ticket_number"),
        "channel_source": StringDatabaseField(name="channel_source"),
        "channel_detail": StringDatabaseField(name="channel_detail", nullable=True),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "status": StringDatabaseField(name="status"),
        "priority": StringDatabaseField(name="priority", nullable=True),
        "anonymous_traits": StringJSONDatabaseField(name="anonymous_traits"),
        "_ai_resolved": BooleanDatabaseField(name="ai_resolved", hidden=True),
        "ai_resolved": ExpressionField(
            name="ai_resolved",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_ai_resolved"])]),
        ),
        "escalation_reason": StringDatabaseField(name="escalation_reason", nullable=True),
        "message_count": IntegerDatabaseField(name="message_count"),
        "unread_customer_count": IntegerDatabaseField(name="unread_customer_count"),
        "unread_team_count": IntegerDatabaseField(name="unread_team_count"),
        "last_message_at": DateTimeDatabaseField(name="last_message_at", nullable=True),
        "last_message_text": StringDatabaseField(name="last_message_text", nullable=True),
        "email_subject": StringDatabaseField(name="email_subject", nullable=True),
        "email_from": StringDatabaseField(name="email_from", nullable=True),
        "session_id": StringDatabaseField(name="session_id", nullable=True),
        "session_context": StringJSONDatabaseField(name="session_context"),
        "sla_due_at": DateTimeDatabaseField(name="sla_due_at", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

early_access_features: PostgresTable = PostgresTable(
    name="early_access_features",
    postgres_table_name="posthog_earlyaccessfeature",
    access_scope="early_access_feature",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "feature_flag_id": IntegerDatabaseField(name="feature_flag_id"),
        "name": StringDatabaseField(name="name"),
        "description": StringDatabaseField(name="description"),
        "stage": StringDatabaseField(name="stage"),
        "documentation_url": StringDatabaseField(name="documentation_url"),
        "created_at": DateTimeDatabaseField(name="created_at"),
    },
)


tasks: PostgresTable = PostgresTable(
    name="tasks",
    postgres_table_name="posthog_task",
    access_scope="task",
    # Mirror the REST API's default filter: internal tasks (signals pipeline, etc.) are not
    # exposed to end users. They are excluded entirely from HogQL.
    predicates=[parse_expr("internal != true")],
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "created_by_id": IntegerDatabaseField(name="created_by_id", nullable=True),
        "github_integration_id": IntegerDatabaseField(name="github_integration_id", nullable=True),
        "task_number": IntegerDatabaseField(name="task_number", nullable=True),
        "title": StringDatabaseField(name="title"),
        "_title_manually_set": BooleanDatabaseField(name="title_manually_set", hidden=True),
        "title_manually_set": ExpressionField(
            name="title_manually_set",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_title_manually_set"])]),
        ),
        "description": StringDatabaseField(name="description"),
        "origin_product": StringDatabaseField(name="origin_product"),
        "repository": StringDatabaseField(name="repository", nullable=True),
        "json_schema": StringJSONDatabaseField(name="json_schema", nullable=True),
        "_internal": BooleanDatabaseField(name="internal", hidden=True),
        "internal": ExpressionField(
            name="internal", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_internal"])])
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "deleted_at": DateTimeDatabaseField(name="deleted_at", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)

task_runs: PostgresTable = PostgresTable(
    name="task_runs",
    postgres_table_name="posthog_task_run",
    access_scope="task",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "task_id": StringDatabaseField(name="task_id"),
        "branch": StringDatabaseField(name="branch", nullable=True),
        "environment": StringDatabaseField(name="environment"),
        "stage": StringDatabaseField(name="stage", nullable=True),
        "status": StringDatabaseField(name="status"),
        "error_message": StringDatabaseField(name="error_message", nullable=True),
        "output": StringJSONDatabaseField(name="output", nullable=True),
        "artifacts": StringJSONDatabaseField(name="artifacts"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
        "completed_at": DateTimeDatabaseField(name="completed_at", nullable=True),
    },
)

sandbox_environments: PostgresTable = PostgresTable(
    name="sandbox_environments",
    postgres_table_name="posthog_sandbox_environment",
    access_scope="task",
    # Mirror the REST API's default filters:
    # - private envs are only visible to their creator (no per-user context here, so excluded entirely)
    # - internal envs (signals pipeline, etc.) are not exposed to end users
    predicates=[parse_expr("private != true"), parse_expr("internal != true")],
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "created_by_id": IntegerDatabaseField(name="created_by_id", nullable=True),
        "name": StringDatabaseField(name="name"),
        "network_access_level": StringDatabaseField(name="network_access_level"),
        "allowed_domains": StringArrayDatabaseField(name="allowed_domains"),
        "_include_default_domains": BooleanDatabaseField(name="include_default_domains", hidden=True),
        "include_default_domains": ExpressionField(
            name="include_default_domains",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_include_default_domains"])]),
        ),
        "repositories": StringArrayDatabaseField(name="repositories"),
        "_private": BooleanDatabaseField(name="private", hidden=True),
        "private": ExpressionField(name="private", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_private"])])),
        "_internal": BooleanDatabaseField(name="internal", hidden=True),
        "internal": ExpressionField(
            name="internal", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_internal"])])
        ),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)


class SystemTables(TableNode):
    name: str = "system"
    children: dict[str, TableNode] = {
        "activity_logs": TableNode(name="activity_logs", table=activity_logs),
        "actions": TableNode(name="actions", table=actions),
        "alerts": TableNode(name="alerts", table=alerts),
        "annotations": TableNode(name="annotations", table=annotations),
        "batch_export_backfills": TableNode(name="batch_export_backfills", table=batch_export_backfills),
        "batch_exports": TableNode(name="batch_exports", table=batch_exports),
        "cohort_calculation_history": TableNode(name="cohort_calculation_history", table=cohort_calculation_history),
        "cohorts": TableNode(name="cohorts", table=cohorts),
        "dashboards": TableNode(name="dashboards", table=dashboards),
        "data_modeling_jobs": TableNode(name="data_modeling_jobs", table=data_modeling_jobs),
        "data_modeling_views": TableNode(name="data_modeling_views", table=data_modeling_views),
        "data_modeling_endpoint_versions": TableNode(name="data_modeling_endpoint_versions", table=endpoint_versions),
        "data_modeling_endpoints": TableNode(name="data_modeling_endpoints", table=endpoints),
        "data_warehouse_sources": TableNode(name="data_warehouse_sources", table=data_warehouse_sources),
        "data_warehouse_tables": TableNode(name="data_warehouse_tables", table=data_warehouse_tables),
        "error_tracking_assignment_rules": TableNode(
            name="error_tracking_assignment_rules", table=error_tracking_assignment_rules
        ),
        "error_tracking_issue_assignments": TableNode(
            name="error_tracking_issue_assignments", table=error_tracking_issue_assignments
        ),
        "error_tracking_issue_fingerprints": TableNode(
            name="error_tracking_issue_fingerprints", table=error_tracking_issue_fingerprints
        ),
        "error_tracking_issues": TableNode(name="error_tracking_issues", table=error_tracking_issues),
        "error_tracking_releases": TableNode(name="error_tracking_releases", table=error_tracking_releases),
        "error_tracking_suppression_rules": TableNode(
            name="error_tracking_suppression_rules", table=error_tracking_suppression_rules
        ),
        "early_access_features": TableNode(name="early_access_features", table=early_access_features),
        "experiments": TableNode(name="experiments", table=experiments),
        "exports": TableNode(name="exports", table=exports),
        "feature_flags": TableNode(name="feature_flags", table=feature_flags),
        "groups": TableNode(name="groups", table=groups),
        "group_type_mappings": TableNode(name="group_type_mappings", table=group_type_mappings),
        "hog_flows": TableNode(name="hog_flows", table=hog_flows),
        "hog_functions": TableNode(name="hog_functions", table=hog_functions),
        "ingestion_warnings": TableNode(name="ingestion_warnings", table=IngestionWarningsTable()),
        "integrations": TableNode(name="integrations", table=integrations),
        "insight_variables": TableNode(name="insight_variables", table=insight_variables),
        "logs_alerts": TableNode(name="logs_alerts", table=logs_alerts),
        "logs_views": TableNode(name="logs_views", table=logs_views),
        "insights": TableNode(name="insights", table=insights),
        "notebooks": TableNode(name="notebooks", table=notebooks),
        "sandbox_environments": TableNode(name="sandbox_environments", table=sandbox_environments),
        "session_recording_playlists": TableNode(name="session_recording_playlists", table=session_recording_playlists),
        "session_recordings": TableNode(name="session_recordings", table=session_recordings),
        "source_schemas": TableNode(name="source_schemas", table=source_schemas),
        "source_sync_jobs": TableNode(name="source_sync_jobs", table=source_sync_jobs),
        "support_tickets": TableNode(name="support_tickets", table=support_tickets),
        "surveys": TableNode(name="surveys", table=surveys),
        "task_runs": TableNode(name="task_runs", table=task_runs),
        "tasks": TableNode(name="tasks", table=tasks),
        "teams": TableNode(name="teams", table=teams),
    }
