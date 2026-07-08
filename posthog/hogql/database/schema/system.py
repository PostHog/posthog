from functools import lru_cache

from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    ExpressionField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    TableNode,
    UUIDDatabaseField,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.database.schema.information_schema import information_schema_node
from posthog.hogql.parser import parse_expr

from posthog.scopes import APIScopeObject

from products.customer_analytics.backend.facade.hogql import (
    account_custom_property_values,
    account_relationship_definitions,
    account_relationships,
    account_resource_notebooks,
    account_tagged_items,
    accounts,
    custom_property_definitions,
)


class IngestionWarningsTable(Table):
    description: str = (
        "Warnings raised while ingesting events (e.g. malformed payloads, dropped properties); "
        "one row per warning. Backed by ClickHouse, not Postgres."
    )
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False, hidden=True),
        "source": StringDatabaseField(
            name="source", nullable=False, description="Pipeline component that raised the warning."
        ),
        "type": StringDatabaseField(
            name="type", nullable=False, description="Warning category, e.g. the rule that fired."
        ),
        "details": StringDatabaseField(
            name="details", nullable=False, description="JSON-encoded context about the specific occurrence."
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="When the warning was raised."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "ingestion_warnings"

    def to_printed_hogql(self):
        return "ingestion_warnings"


batch_export_backfills: PostgresTable = PostgresTable(
    name="batch_export_backfills",
    postgres_table_name="posthog_batchexportbackfill",
    access_scope="batch_export",
    description="Batch export backfill history; one row per backfill that re-exports a historical time range for a batch export.",
    fields={
        "id": StringDatabaseField(name="id", description="Backfill UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "batch_export_id": StringDatabaseField(
            name="batch_export_id", description="Batch export this backfill belongs to; joins to batch_exports.id."
        ),
        "start_at": DateTimeDatabaseField(
            name="start_at",
            nullable=True,
            description="Start of the time range being backfilled (NULL means unbounded).",
        ),
        "end_at": DateTimeDatabaseField(
            name="end_at", nullable=True, description="End of the time range being backfilled (NULL means unbounded)."
        ),
        "status": StringDatabaseField(name="status", description="Backfill status, e.g. Running, Completed, Failed."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the backfill was created."),
        "finished_at": DateTimeDatabaseField(
            name="finished_at", nullable=True, description="When the backfill finished; NULL while still running."
        ),
        "last_updated_at": DateTimeDatabaseField(
            name="last_updated_at", description="When the backfill row was last updated."
        ),
        "total_records_count": IntegerDatabaseField(
            name="total_records_count",
            nullable=True,
            description="Total number of records the backfill is expected to export.",
        ),
    },
)

batch_exports: PostgresTable = PostgresTable(
    name="batch_exports",
    postgres_table_name="posthog_batchexport",
    access_scope="batch_export",
    description="Configured batch exports that periodically ship event/person data to external destinations; one row per batch export.",
    fields={
        "id": StringDatabaseField(name="id", description="Batch export UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="User-given name of the batch export."),
        "model": StringDatabaseField(
            name="model", nullable=True, description="Data model exported, e.g. 'events' or 'persons'."
        ),
        "interval": StringDatabaseField(
            name="interval", description="Export cadence, e.g. 'hour', 'day', 'every 5 minutes'."
        ),
        "_paused": BooleanDatabaseField(name="paused", hidden=True),
        "paused": ExpressionField(
            name="paused",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_paused"])]),
            description="1 if the export is paused, 0 if active.",
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
        "destination_id": StringDatabaseField(
            name="destination_id", description="Identifier of the destination config the export writes to."
        ),
        "timezone": StringDatabaseField(
            name="timezone", description="Timezone used when computing export interval windows."
        ),
        "interval_offset": IntegerDatabaseField(
            name="interval_offset", nullable=True, description="Offset applied to interval windows, in seconds."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the batch export was created."),
        "last_updated_at": DateTimeDatabaseField(
            name="last_updated_at", description="When the config was last updated."
        ),
        "last_paused_at": DateTimeDatabaseField(
            name="last_paused_at", nullable=True, description="When the export was last paused."
        ),
        "start_at": DateTimeDatabaseField(
            name="start_at", nullable=True, description="Earliest data the export covers; NULL means unbounded."
        ),
        "end_at": DateTimeDatabaseField(
            name="end_at", nullable=True, description="Latest data the export covers; NULL means runs indefinitely."
        ),
    },
)

alerts: PostgresTable = PostgresTable(
    name="alerts",
    postgres_table_name="posthog_alertconfiguration",
    access_scope="alert",
    description="Insight alert configurations that notify users when an insight's value crosses a threshold; one row per alert.",
    fields={
        "id": StringDatabaseField(name="id", description="Alert UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="User-given name of the alert."),
        "insight_id": IntegerDatabaseField(
            name="insight_id", description="Insight the alert watches; joins to insights.id."
        ),
        "enabled": BooleanDatabaseField(name="enabled", description="Whether the alert is active."),
        "state": StringDatabaseField(name="state", description="Current alert state, e.g. 'firing' or 'not_firing'."),
        "calculation_interval": StringDatabaseField(
            name="calculation_interval", description="How often the alert is evaluated, e.g. 'daily'."
        ),
        "condition": StringJSONDatabaseField(
            name="condition", description="JSON definition of the threshold/condition to check."
        ),
        "config": StringJSONDatabaseField(
            name="config", description="JSON alert configuration (series, comparison settings, etc.)."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the alert was created."),
        "last_notified_at": DateTimeDatabaseField(
            name="last_notified_at", description="When a notification was last sent."
        ),
        "last_checked_at": DateTimeDatabaseField(
            name="last_checked_at", description="When the alert was last evaluated."
        ),
        "next_check_at": DateTimeDatabaseField(
            name="next_check_at", description="When the alert is next scheduled to be evaluated."
        ),
        "snoozed_until": DateTimeDatabaseField(
            name="snoozed_until", description="Alert is snoozed (no notifications) until this time."
        ),
        "skip_weekend": BooleanDatabaseField(
            name="skip_weekend", description="Whether evaluation is skipped on weekends."
        ),
        "schedule_restriction": StringJSONDatabaseField(
            name="schedule_restriction", description="JSON restricting which days/hours the alert may fire."
        ),
    },
)

cohort_calculation_history: PostgresTable = PostgresTable(
    name="cohort_calculation_history",
    postgres_table_name="posthog_cohortcalculationhistory",
    description="History of cohort membership recalculations; one row per calculation run for a cohort.",
    fields={
        "id": StringDatabaseField(name="id", description="Calculation run UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "cohort_id": IntegerDatabaseField(
            name="cohort_id", description="Cohort that was recalculated; joins to cohorts.id."
        ),
        "count": IntegerDatabaseField(
            name="count", description="Number of people in the cohort after this calculation."
        ),
        "started_at": DateTimeDatabaseField(name="started_at", description="When the calculation started."),
        "finished_at": DateTimeDatabaseField(name="finished_at", description="When the calculation finished."),
        "error_code": StringDatabaseField(
            name="error_code", description="Error code if the calculation failed; empty on success."
        ),
    },
)

cohorts: PostgresTable = PostgresTable(
    name="cohorts",
    postgres_table_name="posthog_cohort",
    description="Cohorts: named groups of people defined by filters or as a static list; one row per cohort.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Cohort id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Cohort name."),
        "description": StringDatabaseField(name="description", description="Cohort description."),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the cohort has been deleted, 0 otherwise.",
        ),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON definition of the cohort's membership filters."
        ),
        "groups": StringJSONDatabaseField(
            name="groups", description="Legacy JSON cohort group definitions (superseded by filters)."
        ),
        "query": StringJSONDatabaseField(
            name="query", description="JSON HogQL query backing the cohort, if defined as a query."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the cohort was created."),
        "last_calculation": DateTimeDatabaseField(
            name="last_calculation", description="When cohort membership was last recalculated."
        ),
        "version": IntegerDatabaseField(name="version", description="Monotonic version bumped on each recalculation."),
        "count": IntegerDatabaseField(name="count", description="Number of people currently in the cohort."),
        "_is_static": BooleanDatabaseField(name="is_static", hidden=True),
        "is_static": ExpressionField(
            name="is_static",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_static"])]),
            description="1 if the cohort is a fixed static list, 0 if dynamically calculated from filters.",
        ),
    },
)

dashboards: PostgresTable = PostgresTable(
    name="dashboards",
    postgres_table_name="posthog_dashboard",
    access_scope="dashboard",
    description="Dashboards: collections of insight tiles; one row per dashboard.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Dashboard id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Dashboard name."),
        "description": StringDatabaseField(name="description", description="Dashboard description."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the dashboard was created."),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the dashboard has been deleted, 0 otherwise.",
        ),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON dashboard-level filters applied to all tiles."
        ),
        "variables": StringJSONDatabaseField(name="variables", description="JSON dashboard-level template variables."),
    },
)

dashboard_tiles: PostgresTable = PostgresTable(
    name="dashboard_tiles",
    postgres_table_name="posthog_dashboardtile",
    access_scope="dashboard",
    # Child of dashboard: object-level access control applies to the parent dashboard, not the tile's own id.
    access_control_id_field="dashboard_id",
    description="Tiles placed on dashboards (insight, text, or button tiles) with their layout; one row per tile.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Tile id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "dashboard_id": IntegerDatabaseField(
            name="dashboard_id", description="Dashboard the tile belongs to; joins to dashboards.id."
        ),
        "insight_id": IntegerDatabaseField(
            name="insight_id",
            nullable=True,
            description="Insight shown by the tile; joins to insights.id (NULL for non-insight tiles).",
        ),
        "text_id": IntegerDatabaseField(
            name="text_id", nullable=True, description="Text content id for text tiles; NULL otherwise."
        ),
        "button_tile_id": StringDatabaseField(
            name="button_tile_id", nullable=True, description="Button content id for button tiles; NULL otherwise."
        ),
        "layouts": StringJSONDatabaseField(
            name="layouts", description="JSON grid layout (position/size) per breakpoint."
        ),
        "color": StringDatabaseField(name="color", nullable=True, description="Optional tile color."),
        "show_description": BooleanDatabaseField(
            name="show_description", nullable=True, description="Whether the insight description is shown on the tile."
        ),
        "transparent_background": BooleanDatabaseField(
            name="transparent_background",
            nullable=True,
            description="Whether the tile renders with a transparent background.",
        ),
        "filters_overrides": StringJSONDatabaseField(
            name="filters_overrides", nullable=True, description="JSON filter overrides applied to this tile only."
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True, nullable=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="ifNull", args=[ast.Field(chain=["_deleted"]), ast.Constant(value=False)]),
        ),
    },
)

insights: PostgresTable = PostgresTable(
    name="insights",
    postgres_table_name="posthog_dashboarditem",
    access_scope="insight",
    description="Saved insights (the model is historically named 'dashboarditem'); one row per insight, including its query definition.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Insight id."),
        "short_id": StringDatabaseField(name="short_id", description="Short URL-safe id used in insight links."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Insight name."),
        "description": StringDatabaseField(name="description", description="Insight description."),
        "filters": StringJSONDatabaseField(name="filters", description="Legacy JSON filter-based insight definition."),
        "query": StringJSONDatabaseField(
            name="query", description="JSON query (HogQL query schema) defining the insight."
        ),
        "query_metadata": StringJSONDatabaseField(
            name="query_metadata", description="JSON metadata derived from the query."
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the insight has been deleted, 0 otherwise.",
        ),
        "_saved": BooleanDatabaseField(name="saved", hidden=True),
        "saved": ExpressionField(
            name="saved",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_saved"])]),
            description="1 if explicitly saved by a user, 0 if a transient/auto-created insight.",
        ),
        "_favorited": BooleanDatabaseField(name="favorited", hidden=True),
        "favorited": ExpressionField(
            name="favorited",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_favorited"])]),
            description="1 if the insight is marked as a favorite, 0 otherwise.",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the insight was created."),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the insight."
        ),
        "last_modified_at": DateTimeDatabaseField(
            name="last_modified_at", description="When the insight definition was last changed."
        ),
        "last_modified_by_id": IntegerDatabaseField(
            name="last_modified_by_id", nullable=True, description="User who last modified the insight."
        ),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", description="When the row was last updated (any field)."
        ),
    },
)

experiments: PostgresTable = PostgresTable(
    name="experiments",
    postgres_table_name="posthog_experiment",
    access_scope="experiment",
    description="A/B test experiments; one row per experiment, linked to the feature flag that controls variant assignment.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Experiment id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Experiment name."),
        "description": StringDatabaseField(name="description", description="Experiment description/hypothesis."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the experiment was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the experiment was last updated."),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON definition of the experiment's goal metric filters."
        ),
        "parameters": StringJSONDatabaseField(
            name="parameters",
            description="JSON experiment parameters (e.g. sample size settings). Flag config such as "
            "variants lives on the linked feature flag's filters, not in this column.",
        ),
        "start_date": DateTimeDatabaseField(
            name="start_date", description="When the experiment was launched; NULL if not started."
        ),
        "end_date": DateTimeDatabaseField(
            name="end_date", description="When the experiment was concluded; NULL if still running."
        ),
        "_archived": BooleanDatabaseField(name="archived", hidden=True),
        "archived": ExpressionField(
            name="archived",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_archived"])]),
            description="1 if the experiment is archived, 0 otherwise.",
        ),
        "feature_flag_id": IntegerDatabaseField(
            name="feature_flag_id",
            description="Feature flag controlling variant assignment; joins to feature_flags.id.",
        ),
    },
)

data_warehouse_sources: PostgresTable = PostgresTable(
    name="data_warehouse_sources",
    postgres_table_name="posthog_externaldatasource",
    access_scope="external_data_source",
    description="Configured data warehouse import sources (Stripe, Postgres, Hubspot, etc.); one row per connected source.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Source id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "source_type": StringDatabaseField(
            name="source_type", description="Source connector type, e.g. 'Stripe', 'Postgres', 'Hubspot'."
        ),
        "prefix": StringDatabaseField(
            name="prefix", description="Table-name prefix applied to all tables synced from this source."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the source was connected."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the source config was last updated."),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the source has been deleted, 0 otherwise.",
        ),
        "deleted_at": DateTimeDatabaseField(
            name="deleted_at", description="When the source was deleted; NULL if not deleted."
        ),
    },
)

data_modeling_views: PostgresTable = PostgresTable(
    name="data_modeling_views",
    postgres_table_name="posthog_datawarehousesavedquery",
    description="Saved queries / data-modeling views built on top of warehouse data; one row per view, optionally materialized.",
    fields={
        "id": StringDatabaseField(name="id", description="View UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="View name, used to reference it in queries."),
        "status": StringDatabaseField(
            name="status", description="Materialization status, e.g. Running, Completed, Failed."
        ),
        "columns": StringJSONDatabaseField(name="columns", description="JSON schema of the view's output columns."),
        "query": StringJSONDatabaseField(name="query", description="JSON HogQL query defining the view."),
        "last_run_at": DateTimeDatabaseField(
            name="last_run_at", description="When the view was last materialized/run."
        ),
        "_is_materialized": BooleanDatabaseField(name="is_materialized", hidden=True),
        "is_materialized": ExpressionField(
            name="is_materialized",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_materialized"])]),
            description="1 if the view is materialized to a backing table, 0 if computed on the fly.",
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the view has been deleted, 0 otherwise.",
        ),
        "deleted_at": DateTimeDatabaseField(
            name="deleted_at", description="When the view was deleted; NULL if not deleted."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the view was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the view was last updated."),
    },
)

data_warehouse_tables: PostgresTable = PostgresTable(
    name="data_warehouse_tables",
    postgres_table_name="posthog_datawarehousetable",
    description="Tables synced into the data warehouse from external sources; one row per warehouse table.",
    fields={
        "id": StringDatabaseField(name="id", description="Warehouse table UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Warehouse table name (includes the source prefix)."),
        "columns": StringJSONDatabaseField(name="columns", description="JSON schema of the table's columns."),
        "row_count": IntegerDatabaseField(name="row_count", description="Approximate number of rows in the table."),
        "external_data_source_id": StringDatabaseField(
            name="external_data_source_id",
            description="Source that produced this table; joins to data_warehouse_sources.id.",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the table was first synced."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the table metadata was last updated."),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the table has been deleted, 0 otherwise.",
        ),
        "deleted_at": DateTimeDatabaseField(
            name="deleted_at", description="When the table was deleted; NULL if not deleted."
        ),
    },
)

source_schemas: PostgresTable = PostgresTable(
    name="source_schemas",
    postgres_table_name="posthog_externaldataschema",
    access_scope="external_data_source",
    # Child of external_data_source: object-level access control applies to the parent source, not the schema's own id.
    access_control_id_field="source_id",
    description="Per-table sync configuration within a data warehouse source (which table to import and how); one row per source table.",
    fields={
        "id": StringDatabaseField(name="id", description="Schema UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Name of the table/endpoint in the external source."),
        "source_id": StringDatabaseField(
            name="source_id", description="Parent source; joins to data_warehouse_sources.id."
        ),
        "table_id": StringDatabaseField(
            name="table_id", description="Resulting warehouse table; joins to data_warehouse_tables.id."
        ),
        "should_sync": BooleanDatabaseField(
            name="should_sync", description="Whether this table is enabled for syncing."
        ),
        "status": StringDatabaseField(
            name="status", description="Latest sync status for this table, e.g. Running, Completed, Error."
        ),
        "sync_type": StringDatabaseField(
            name="sync_type", description="Sync strategy, e.g. 'full_refresh' or 'incremental'."
        ),
        "last_synced_at": DateTimeDatabaseField(
            name="last_synced_at", description="When this table last finished syncing."
        ),
        "latest_error": StringDatabaseField(name="latest_error", description="Most recent sync error message, if any."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the schema config was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the schema config was last updated."),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the schema config has been deleted, 0 otherwise.",
        ),
        "deleted_at": DateTimeDatabaseField(name="deleted_at", description="When it was deleted; NULL if not deleted."),
    },
)

source_sync_jobs: PostgresTable = PostgresTable(
    name="source_sync_jobs",
    postgres_table_name="posthog_externaldatajob",
    access_scope="external_data_source",
    # Child of external_data_source: object-level access control applies to the parent source, not the job's own id.
    access_control_id_field="pipeline_id",
    description="Data warehouse sync job runs; one row per sync attempt of a source schema, with rows synced and outcome.",
    fields={
        "id": StringDatabaseField(name="id", description="Sync job UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "pipeline_id": StringDatabaseField(
            name="pipeline_id", description="Source whose pipeline ran; joins to data_warehouse_sources.id."
        ),
        "schema_id": StringDatabaseField(
            name="schema_id", description="Source schema being synced; joins to source_schemas.id."
        ),
        "status": StringDatabaseField(name="status", description="Job status, e.g. Running, Completed, Failed."),
        "rows_synced": IntegerDatabaseField(name="rows_synced", description="Number of rows synced by this job."),
        "billable": BooleanDatabaseField(name="billable", description="Whether the rows synced count toward billing."),
        "latest_error": StringDatabaseField(name="latest_error", description="Error message if the job failed."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the job started."),
        "finished_at": DateTimeDatabaseField(
            name="finished_at", description="When the job finished; NULL while running."
        ),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the job row was last updated."),
    },
)

endpoint_versions: PostgresTable = PostgresTable(
    name="data_modeling_endpoint_versions",
    postgres_table_name="endpoints_endpointversion",
    access_scope="endpoint",
    # Child of endpoint: object-level access control applies to the parent endpoint, not the version's own id.
    access_control_id_field="endpoint_id",
    description="Versioned query definitions for data-modeling endpoints (saved, callable HogQL queries); one row per endpoint version.",
    fields={
        "id": StringDatabaseField(name="id", description="Endpoint version UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "endpoint_id": StringDatabaseField(
            name="endpoint_id", description="Parent endpoint; joins to data_modeling_endpoints.id."
        ),
        "version": IntegerDatabaseField(name="version", description="Version number within the endpoint."),
        "description": StringDatabaseField(name="description", description="Description of this endpoint version."),
        "query": StringJSONDatabaseField(name="query", description="JSON HogQL query executed by this version."),
        "data_freshness_seconds": IntegerDatabaseField(
            name="data_freshness_seconds", description="Max age, in seconds, of cached results before re-running."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When this version was created."),
        "_is_active": BooleanDatabaseField(name="is_active", hidden=True),
        "is_active": ExpressionField(
            name="is_active",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_active"])]),
            description="1 if this is the currently served version, 0 otherwise.",
        ),
        "columns": StringJSONDatabaseField(name="columns", description="JSON schema of the version's output columns."),
    },
)

endpoints: PostgresTable = PostgresTable(
    name="data_modeling_endpoints",
    postgres_table_name="endpoints_endpoint",
    predicates=[parse_expr("deleted != true")],
    access_scope="endpoint",
    description="Data-modeling endpoints: named, callable saved queries; one row per endpoint (deleted endpoints are excluded).",
    fields={
        "id": StringDatabaseField(name="id", description="Endpoint UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Endpoint name, used to call it."),
        "_is_active": BooleanDatabaseField(name="is_active", hidden=True),
        "is_active": ExpressionField(
            name="is_active",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_active"])]),
            description="1 if the endpoint is active and callable, 0 otherwise.",
        ),
        "current_version": IntegerDatabaseField(
            name="current_version",
            description="Version number currently served; joins to data_modeling_endpoint_versions.version.",
        ),
        "derived_from_insight": StringDatabaseField(
            name="derived_from_insight", description="Short id of the insight this endpoint was created from, if any."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the endpoint was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the endpoint was last updated."),
        "last_executed_at": DateTimeDatabaseField(
            name="last_executed_at", description="When the endpoint was last called/executed."
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(name="deleted", expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])])),
    },
)

feature_flags: PostgresTable = PostgresTable(
    name="feature_flags",
    postgres_table_name="posthog_featureflag",
    access_scope="feature_flag",
    description="Feature flags; one row per flag, with its targeting filters and rollout configuration.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Flag id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "key": StringDatabaseField(name="key", description="Flag key used by SDKs to evaluate the flag."),
        "name": StringDatabaseField(name="name", description="Human-readable flag name/description."),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON targeting rules, variants, and release conditions."
        ),
        "rollout_percentage": IntegerDatabaseField(
            name="rollout_percentage",
            description="Top-level rollout percentage (0-100); detailed rules live in filters.",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the flag was created."),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the flag has been deleted, 0 otherwise.",
        ),
    },
)

groups: PostgresTable = PostgresTable(
    name="groups",
    postgres_table_name="posthog_group",
    description="Group analytics entities (e.g. companies, projects); one row per group instance.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Internal group row id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "group_key": StringDatabaseField(
            name="group_key", description="Identifier of the group within its type, e.g. a company id."
        ),
        "group_type_index": IntegerDatabaseField(
            name="group_type_index", description="Which group type (0-4) this group belongs to."
        ),
        "group_properties": StringJSONDatabaseField(
            name="group_properties", description="JSON map of the group's properties."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the group was first seen."),
    },
)

group_type_mappings: PostgresTable = PostgresTable(
    name="group_type_mappings",
    postgres_table_name="posthog_grouptypemapping",
    description="Mapping of group type indexes (0-4) to their names; one row per configured group type.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Mapping row id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "group_type": StringDatabaseField(
            name="group_type", description="Name of the group type, e.g. 'company' or 'project'."
        ),
        "name_singular": StringDatabaseField(
            name="name_singular", description="Singular display label, e.g. 'organization'."
        ),
        "name_plural": StringDatabaseField(
            name="name_plural", description="Plural display label, e.g. 'organizations'."
        ),
    },
)

integrations: PostgresTable = PostgresTable(
    name="integrations",
    postgres_table_name="posthog_integration",
    access_scope="integration",
    description="Third-party integrations connected to the project (Slack, GitHub, etc.); one row per integration.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Integration id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "kind": StringDatabaseField(name="kind", description="Integration type, e.g. 'slack', 'github', 'salesforce'."),
        "integration_id": StringDatabaseField(
            name="integration_id", description="Identifier of the account/workspace in the external system."
        ),
        "config": StringJSONDatabaseField(name="config", description="JSON non-sensitive integration config."),
        "errors": StringDatabaseField(
            name="errors", description="Most recent error encountered using the integration."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the integration was connected."),
        "created_by_id": IntegerDatabaseField(name="created_by_id", description="User who connected the integration."),
    },
)

integration_repository_cache: PostgresTable = PostgresTable(
    name="integration_repository_cache",
    postgres_table_name="posthog_integrationrepositorycacheentry",
    access_scope="integration",
    description="Cached metadata about GitHub repositories accessible via an integration; one row per repository.",
    fields={
        "id": StringDatabaseField(name="id", description="Cache entry UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "integration_id": IntegerDatabaseField(
            name="integration_id",
            nullable=True,
            description="Org-level integration this repo belongs to; joins to integrations.id.",
        ),
        "user_integration_id": IntegerDatabaseField(
            name="user_integration_id", nullable=True, description="User-level integration this repo belongs to."
        ),
        "full_name": StringDatabaseField(name="full_name", description="Repository full name, e.g. 'owner/repo'."),
        "description": StringDatabaseField(name="description", nullable=True, description="Repository description."),
        "topics": StringJSONDatabaseField(name="topics", description="JSON array of repository topics/tags."),
        "archived": BooleanDatabaseField(name="archived", description="Whether the repository is archived on GitHub."),
        "fork": BooleanDatabaseField(name="fork", description="Whether the repository is a fork."),
        "primary_language": StringDatabaseField(
            name="primary_language", nullable=True, description="Primary programming language."
        ),
        "default_branch": StringDatabaseField(name="default_branch", description="Default branch name, e.g. 'main'."),
        "default_branch_sha": StringDatabaseField(
            name="default_branch_sha", description="Commit SHA at the head of the default branch."
        ),
        "readme": StringDatabaseField(name="readme", description="Cached README contents."),
        "tree_paths": StringDatabaseField(
            name="tree_paths", description="Cached list of file paths in the repository tree."
        ),
        "tree_truncated": BooleanDatabaseField(
            name="tree_truncated", description="Whether the cached file tree was truncated."
        ),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the cache entry was last refreshed."),
    },
)

insight_variables: PostgresTable = PostgresTable(
    name="insight_variables",
    postgres_table_name="posthog_insightvariable",
    description="Reusable insight/dashboard template variables; one row per variable.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Variable id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Display name of the variable."),
        "type": StringDatabaseField(name="type", description="Variable type, e.g. 'String', 'Number', 'List', 'Date'."),
        "code_name": StringDatabaseField(
            name="code_name", description="Identifier used to reference the variable in queries."
        ),
        "values": StringJSONDatabaseField(
            name="values", description="JSON list of allowed values, for list-type variables."
        ),
        "default_value": StringJSONDatabaseField(
            name="default_value", description="JSON default value of the variable."
        ),
    },
)

session_recording_playlists: PostgresTable = PostgresTable(
    name="session_recording_playlists",
    postgres_table_name="posthog_sessionrecordingplaylist",
    access_scope="session_recording_playlist",
    description="Saved playlists/collections of session recordings, defined by filters or pinned recordings; one row per playlist.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Playlist id."),
        "short_id": StringDatabaseField(name="short_id", description="Short URL-safe id used in playlist links."),
        "name": StringDatabaseField(name="name", description="User-given playlist name."),
        "derived_name": StringDatabaseField(
            name="derived_name", description="Auto-generated name used when no name is set."
        ),
        "description": StringDatabaseField(name="description", description="Playlist description."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "_pinned": BooleanDatabaseField(name="pinned", hidden=True),
        "pinned": ExpressionField(
            name="pinned",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_pinned"])]),
            description="1 if the playlist is pinned, 0 otherwise.",
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the playlist has been deleted, 0 otherwise.",
        ),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON filters defining which recordings are in the playlist."
        ),
        "type": StringDatabaseField(
            name="type", description="Playlist type, e.g. filter-based or a collection of pinned recordings."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the playlist was created."),
        "created_by_id": IntegerDatabaseField(name="created_by_id", description="User who created the playlist."),
        "last_modified_at": DateTimeDatabaseField(
            name="last_modified_at", description="When the playlist was last modified."
        ),
        "last_modified_by_id": IntegerDatabaseField(
            name="last_modified_by_id", description="User who last modified the playlist."
        ),
    },
)

session_recordings: PostgresTable = PostgresTable(
    name="session_recordings",
    postgres_table_name="posthog_sessionrecording",
    access_scope="session_recording",
    description="Session recording metadata (durations, activity counts); one row per recorded session. The recording payload itself lives in object storage, not here.",
    fields={
        "id": StringDatabaseField(name="id", description="Recording row UUID."),
        "session_id": StringDatabaseField(
            name="session_id", description="Session identifier; matches events.$session_id."
        ),
        "team_id": IntegerDatabaseField(name="team_id"),
        "distinct_id": StringDatabaseField(name="distinct_id", description="Distinct id of the user/device recorded."),
        "duration": IntegerDatabaseField(
            name="duration", description="Total recording length in seconds (active + inactive)."
        ),
        "active_seconds": IntegerDatabaseField(name="active_seconds", description="Seconds of active user engagement."),
        "inactive_seconds": IntegerDatabaseField(name="inactive_seconds", description="Seconds with no user activity."),
        "start_time": DateTimeDatabaseField(name="start_time", description="When the recording started."),
        "end_time": DateTimeDatabaseField(name="end_time", description="When the recording ended."),
        "click_count": IntegerDatabaseField(name="click_count", description="Number of clicks captured."),
        "keypress_count": IntegerDatabaseField(name="keypress_count", description="Number of keypresses captured."),
        "mouse_activity_count": IntegerDatabaseField(
            name="mouse_activity_count", description="Number of mouse-activity events captured."
        ),
        "console_log_count": IntegerDatabaseField(
            name="console_log_count", description="Number of console.log messages captured."
        ),
        "console_warn_count": IntegerDatabaseField(
            name="console_warn_count", description="Number of console.warn messages captured."
        ),
        "console_error_count": IntegerDatabaseField(
            name="console_error_count", description="Number of console.error messages captured."
        ),
        "start_url": StringDatabaseField(name="start_url", description="URL where the recording started."),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the recording has been deleted, 0 otherwise.",
        ),
        "created_at": DateTimeDatabaseField(
            name="created_at", description="When the recording metadata row was created."
        ),
        "retention_period_days": IntegerDatabaseField(
            name="retention_period_days", description="How long the recording is retained, in days."
        ),
        "storage_version": StringDatabaseField(
            name="storage_version", description="Storage format version of the recording payload."
        ),
    },
)

surveys: PostgresTable = PostgresTable(
    name="surveys",
    postgres_table_name="posthog_survey",
    access_scope="survey",
    description="In-app surveys; one row per survey, including its questions and display configuration.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Survey id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Survey name."),
        "type": StringDatabaseField(name="type", description="Survey delivery type, e.g. 'popover', 'api', 'widget'."),
        "questions": StringJSONDatabaseField(name="questions", description="JSON array of the survey's questions."),
        "appearance": StringJSONDatabaseField(name="appearance", description="JSON styling/appearance configuration."),
        "start_date": DateTimeDatabaseField(
            name="start_date", description="When the survey was launched; NULL if not started."
        ),
        "end_date": DateTimeDatabaseField(
            name="end_date", description="When the survey was stopped; NULL if still running."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the survey was created."),
    },
)

teams: PostgresTable = PostgresTable(
    name="teams",
    postgres_table_name="posthog_team",
    description="Projects/teams (a PostHog 'team' is a project); typically just the caller's own team.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Team/project id."),
        "team_id": IntegerDatabaseField(name="id", description="Alias of id for consistency with other tables."),
        "name": StringDatabaseField(name="name", description="Project name."),
        "timezone": StringDatabaseField(name="timezone", description="Project timezone used for date bucketing."),
        "test_account_filters": StringJSONDatabaseField(
            name="test_account_filters", description="JSON filters defining internal/test accounts to exclude."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the project was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the project was last updated."),
    },
)

exports: PostgresTable = PostgresTable(
    name="exports",
    postgres_table_name="posthog_exportedasset",
    description="One-off exported assets (CSV/PNG/PDF of insights, etc.); one row per exported asset.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Exported asset id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "export_format": StringDatabaseField(
            name="export_format", description="MIME type of the export, e.g. 'text/csv', 'image/png'."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the export was created."),
        "export_context": StringJSONDatabaseField(
            name="export_context", description="JSON describing what was exported (query, source, etc.)."
        ),
    },
)

# The project's virtual file tree (posthog_filesystem). Channels are folders and
# tasks/canvases are filed under them by `path`; `surface` separates products
# (e.g. "web" vs "desktop"). Scoped to a channel via startsWith(path, ...).
file_system: PostgresTable = PostgresTable(
    name="file_system",
    postgres_table_name="posthog_filesystem",
    description="The project's virtual file tree backing the navigation/'products' UI; one row per node (folder or item) addressed by path.",
    fields={
        "id": StringDatabaseField(name="id", description="File-system node UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "path": StringDatabaseField(name="path", description="Slash-delimited path of the node in the tree."),
        "depth": IntegerDatabaseField(name="depth", nullable=True, description="Number of path segments (tree depth)."),
        "type": StringDatabaseField(name="type", description="Node type, e.g. a folder or a specific item kind."),
        "ref": StringDatabaseField(
            name="ref", nullable=True, description="Id of the underlying object the node points to."
        ),
        "href": StringDatabaseField(name="href", nullable=True, description="URL the node links to in the app."),
        "meta": StringJSONDatabaseField(name="meta", nullable=True, description="JSON metadata about the node."),
        "surface": StringDatabaseField(
            name="surface", nullable=True, description="Product surface the node belongs to, e.g. 'web' or 'desktop'."
        ),
        "shortcut": BooleanDatabaseField(
            name="shortcut", nullable=True, description="Whether the node is a shortcut to another node."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the node was created."),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the node."
        ),
    },
)

activity_logs: PostgresTable = PostgresTable(
    name="activity_logs",
    postgres_table_name="posthog_activitylog",
    access_scope="activity_log",
    description="Audit trail of changes to objects (insights, flags, dashboards, etc.); one row per logged activity.",
    fields={
        "id": StringDatabaseField(name="id", description="Activity log entry UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "activity": StringDatabaseField(
            name="activity", description="Action performed, e.g. 'created', 'updated', 'deleted'."
        ),
        "item_id": StringDatabaseField(name="item_id", description="Id of the object the activity is about."),
        "scope": StringDatabaseField(
            name="scope", description="Type of object affected, e.g. 'Insight', 'FeatureFlag', 'Dashboard'."
        ),
        "detail": StringJSONDatabaseField(
            name="detail", description="JSON detail of what changed (field-level diffs, context)."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the activity occurred."),
    },
)

actions: PostgresTable = PostgresTable(
    name="actions",
    postgres_table_name="posthog_action",
    access_scope="action",
    description="Actions: named event matchers that group raw events into meaningful user actions; one row per action.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Action id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Action name."),
        "description": StringDatabaseField(name="description", description="Action description."),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the action has been deleted, 0 otherwise.",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the action was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the action was last updated."),
        "steps_json": StringJSONDatabaseField(
            name="steps_json", description="JSON array of match steps (event/selector/url conditions)."
        ),
    },
)

annotations: PostgresTable = PostgresTable(
    name="annotations",
    postgres_table_name="posthog_annotation",
    access_scope="annotation",
    description="Annotations: dated notes overlaid on insight/dashboard charts; one row per annotation.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Annotation id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "content": StringDatabaseField(name="content", nullable=True, description="Annotation text."),
        "scope": StringDatabaseField(
            name="scope", description="Where the annotation applies, e.g. 'project', 'dashboard', 'insight'."
        ),
        "creation_type": StringDatabaseField(
            name="creation_type", description="How the annotation was created, e.g. user-created vs GitHub."
        ),
        "date_marker": DateTimeDatabaseField(
            name="date_marker", nullable=True, description="The point in time the annotation marks on a chart."
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the annotation has been deleted, 0 otherwise.",
        ),
        "dashboard_item_id": IntegerDatabaseField(
            name="dashboard_item_id",
            nullable=True,
            description="Insight this annotation is scoped to; joins to insights.id.",
        ),
        "dashboard_id": IntegerDatabaseField(
            name="dashboard_id",
            nullable=True,
            description="Dashboard this annotation is scoped to; joins to dashboards.id.",
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the annotation."
        ),
        "created_at": DateTimeDatabaseField(
            name="created_at", nullable=True, description="When the annotation was created."
        ),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the annotation was last updated."),
    },
)

hog_flows: PostgresTable = PostgresTable(
    name="hog_flows",
    postgres_table_name="posthog_hogflow",
    access_scope="hog_flow",
    description="Hog flows: multi-step automation/messaging workflows; one row per flow, with its graph of actions and edges.",
    fields={
        "id": StringDatabaseField(name="id", description="Flow UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Flow name."),
        "description": StringDatabaseField(name="description", description="Flow description."),
        "status": StringDatabaseField(name="status", description="Flow status, e.g. 'active', 'draft', 'archived'."),
        "version": IntegerDatabaseField(name="version", description="Flow version number."),
        "exit_condition": StringDatabaseField(
            name="exit_condition", description="Condition that causes a person to exit the flow."
        ),
        "trigger": StringJSONDatabaseField(
            name="trigger", description="JSON definition of what enrolls people into the flow."
        ),
        "edges": StringJSONDatabaseField(name="edges", description="JSON edges connecting actions in the flow graph."),
        "actions": StringJSONDatabaseField(name="actions", description="JSON nodes/actions that make up the flow."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the flow was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the flow was last updated."),
    },
)

hog_functions: PostgresTable = PostgresTable(
    name="hog_functions",
    postgres_table_name="posthog_hogfunction",
    access_scope="hog_function",
    description="Hog functions: destinations/transformations in the CDP pipeline (written in Hog); one row per function.",
    fields={
        "id": StringDatabaseField(name="id", description="Function UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Function name."),
        "description": StringDatabaseField(name="description", description="Function description."),
        "type": StringDatabaseField(
            name="type", description="Function type, e.g. 'destination', 'transformation', 'site_app'."
        ),
        "_enabled": BooleanDatabaseField(name="enabled", hidden=True),
        "enabled": ExpressionField(
            name="enabled",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_enabled"])]),
            description="1 if the function is enabled, 0 otherwise.",
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the function has been deleted, 0 otherwise.",
        ),
        "icon_url": StringDatabaseField(name="icon_url", description="URL of the function's icon."),
        "template_id": StringDatabaseField(
            name="template_id", description="Id of the template this function was created from."
        ),
        "execution_order": IntegerDatabaseField(
            name="execution_order", description="Order in which the function runs relative to others of its type."
        ),
        "inputs_schema": StringJSONDatabaseField(
            name="inputs_schema", description="JSON schema describing the function's configurable inputs."
        ),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON filters deciding which events the function runs on."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the function was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the function was last updated."),
    },
)


def _notebook_content_or_empty_object_expr() -> ast.Expr:
    return ast.Call(name="ifNull", args=[ast.Field(chain=["content"]), ast.Constant(value="{}")])


def _first_notebook_content_node_expr() -> ast.Expr:
    return ast.ArrayAccess(
        array=ast.Call(
            name="JSONExtractArrayRaw",
            args=[_notebook_content_or_empty_object_expr(), ast.Constant(value="content")],
        ),
        property=ast.Constant(value=1),
    )


def _notebook_markdown_expr() -> ast.Expr:
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(
                left=ast.Call(
                    name="JSONExtractString",
                    args=[_first_notebook_content_node_expr(), ast.Constant(value="type")],
                ),
                right=ast.Constant(value="ph-markdown-notebook"),
                op=ast.CompareOperationOp.Eq,
            ),
            ast.Call(
                name="JSONExtractString",
                args=[
                    _first_notebook_content_node_expr(),
                    ast.Constant(value="attrs"),
                    ast.Constant(value="markdown"),
                ],
            ),
            ast.Constant(value=None),
        ],
    )


notebooks: PostgresTable = PostgresTable(
    name="notebooks",
    postgres_table_name="posthog_notebook",
    access_scope="notebook",
    description="Notebooks: rich-text documents that embed insights, recordings, and queries; one row per notebook.",
    fields={
        "id": StringDatabaseField(name="id", description="Notebook UUID."),
        "short_id": StringDatabaseField(name="short_id", description="Short URL-safe id used in notebook links."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "title": StringDatabaseField(name="title", description="Notebook title."),
        "content": StringJSONDatabaseField(
            name="content", description="JSON rich-text document (ProseMirror) content."
        ),
        "markdown": ExpressionField(
            name="markdown",
            nullable=True,
            expr=_notebook_markdown_expr(),
            description="Markdown source for markdown notebooks; NULL for legacy rich-text notebooks.",
        ),
        "text_content": StringDatabaseField(
            name="text_content", description="Plain-text rendering of the notebook, for search."
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the notebook has been deleted, 0 otherwise.",
        ),
        "visibility": StringDatabaseField(
            name="visibility", description="Visibility setting, e.g. 'private' or shared."
        ),
        "version": IntegerDatabaseField(name="version", description="Notebook version number."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the notebook was created."),
        "last_modified_at": DateTimeDatabaseField(
            name="last_modified_at", description="When the notebook was last modified."
        ),
    },
)

data_modeling_jobs: PostgresTable = PostgresTable(
    name="data_modeling_jobs",
    postgres_table_name="posthog_datamodelingjob",
    description="Materialization job runs for data-modeling views; one row per run that materializes a view.",
    fields={
        "id": StringDatabaseField(name="id", description="Job UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "data_modeling_view_id": StringDatabaseField(
            name="saved_query_id", description="View being materialized; joins to data_modeling_views.id."
        ),
        "status": StringDatabaseField(name="status", description="Job status, e.g. Running, Completed, Failed."),
        "rows_materialized": IntegerDatabaseField(
            name="rows_materialized", description="Number of rows written so far."
        ),
        "rows_expected": IntegerDatabaseField(name="rows_expected", description="Number of rows expected for the run."),
        "error": StringDatabaseField(name="error", description="Error message if the job failed."),
        "storage_delta_mib": FloatDatabaseField(
            name="storage_delta_mib", description="Change in materialized storage size, in MiB."
        ),
        "last_run_at": DateTimeDatabaseField(name="last_run_at", description="When the job last ran."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the job was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the job row was last updated."),
    },
)

error_tracking_issues: PostgresTable = PostgresTable(
    name="error_tracking_issues",
    postgres_table_name="posthog_errortrackingissue",
    access_scope="error_tracking",
    description="Error tracking issues: grouped exceptions/errors; one row per issue.",
    fields={
        "id": StringDatabaseField(name="id", description="Issue UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the issue was first created."),
        "status": StringDatabaseField(
            name="status", description="Issue status, e.g. 'active', 'resolved', 'suppressed'."
        ),
        "name": StringDatabaseField(name="name", description="Issue title (usually the exception type/message)."),
        "description": StringDatabaseField(name="description", description="Issue description."),
    },
)

error_tracking_issue_assignments: PostgresTable = PostgresTable(
    name="error_tracking_issue_assignments",
    postgres_table_name="posthog_errortrackingissueassignment",
    access_scope="error_tracking",
    description="Assignments of error tracking issues to a user or role; one row per assignment.",
    fields={
        "id": StringDatabaseField(name="id", description="Assignment UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "issue_id": StringDatabaseField(
            name="issue_id", description="Issue assigned; joins to error_tracking_issues.id."
        ),
        "user_id": IntegerDatabaseField(
            name="user_id", description="User the issue is assigned to (if assigned to a user)."
        ),
        "role_id": StringDatabaseField(
            name="role_id", description="Role the issue is assigned to (if assigned to a role)."
        ),
    },
)

error_tracking_issue_fingerprints: PostgresTable = PostgresTable(
    name="error_tracking_issue_fingerprints",
    postgres_table_name="posthog_errortrackingissuefingerprintv2",
    access_scope="error_tracking",
    description="Fingerprints that map individual exceptions to an issue (the grouping key); one row per fingerprint.",
    fields={
        "id": StringDatabaseField(name="id", description="Fingerprint row UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "issue_id": StringDatabaseField(
            name="issue_id", description="Issue this fingerprint belongs to; joins to error_tracking_issues.id."
        ),
        "fingerprint": StringDatabaseField(
            name="fingerprint", description="Hash that groups matching exceptions into the issue."
        ),
        "first_seen": DateTimeDatabaseField(name="first_seen", description="When this fingerprint was first seen."),
    },
)

error_tracking_assignment_rules: PostgresTable = PostgresTable(
    name="error_tracking_assignment_rules",
    postgres_table_name="posthog_errortrackingassignmentrule",
    access_scope="error_tracking",
    description="Rules that auto-assign new error tracking issues to a user or role based on filters; one row per rule.",
    fields={
        "id": StringDatabaseField(name="id", description="Rule UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "user_id": IntegerDatabaseField(
            name="user_id", nullable=True, description="User matched issues are assigned to."
        ),
        "role_id": StringDatabaseField(
            name="role_id", nullable=True, description="Role matched issues are assigned to."
        ),
        "order_key": IntegerDatabaseField(name="order_key", description="Evaluation order; lower runs first."),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON conditions an issue must match for the rule to apply."
        ),
        "bytecode": StringJSONDatabaseField(name="bytecode", description="Compiled Hog bytecode for the filters."),
        "disabled_data": StringJSONDatabaseField(
            name="disabled_data", nullable=True, description="JSON state when the rule is disabled; NULL when active."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the rule was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the rule was last updated."),
    },
)

error_tracking_bypass_rules: PostgresTable = PostgresTable(
    name="error_tracking_bypass_rules",
    postgres_table_name="posthog_errortrackingbypassrule",
    access_scope="error_tracking",
    description="Rules that exempt matching exceptions from error tracking rate limits; one row per rule.",
    fields={
        "id": StringDatabaseField(name="id", description="Rule UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "order_key": IntegerDatabaseField(name="order_key", description="Evaluation order; lower runs first."),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON conditions an exception must match for the rule to apply."
        ),
        "bytecode": StringJSONDatabaseField(
            name="bytecode", nullable=True, description="Compiled Hog bytecode for the filters."
        ),
        "disabled_data": StringJSONDatabaseField(
            name="disabled_data", nullable=True, description="JSON state when the rule is disabled; NULL when active."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the rule was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the rule was last updated."),
    },
)

error_tracking_suppression_rules: PostgresTable = PostgresTable(
    name="error_tracking_suppression_rules",
    postgres_table_name="posthog_errortrackingsuppressionrule",
    access_scope="error_tracking",
    description="Rules that suppress or sample matching exceptions before they create issues; one row per rule.",
    fields={
        "id": StringDatabaseField(name="id", description="Rule UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "order_key": IntegerDatabaseField(name="order_key", description="Evaluation order; lower runs first."),
        "sampling_rate": FloatDatabaseField(
            name="sampling_rate", description="Fraction (0-1) of matching exceptions to keep; the rest are suppressed."
        ),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON conditions an exception must match for the rule to apply."
        ),
        "bytecode": StringJSONDatabaseField(
            name="bytecode", nullable=True, description="Compiled Hog bytecode for the filters."
        ),
        "disabled_data": StringJSONDatabaseField(
            name="disabled_data", nullable=True, description="JSON state when the rule is disabled; NULL when active."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the rule was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the rule was last updated."),
    },
)

error_tracking_releases: PostgresTable = PostgresTable(
    name="error_tracking_releases",
    postgres_table_name="posthog_errortrackingrelease",
    access_scope="error_tracking",
    description="Code releases tracked for error attribution and source-map matching; one row per release.",
    fields={
        "id": StringDatabaseField(name="id", description="Release UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "hash_id": StringDatabaseField(name="hash_id", description="Hash identifying the release build."),
        "version": StringDatabaseField(name="version", description="Human-readable release version."),
        "project": StringDatabaseField(name="project", description="Project/app the release belongs to."),
        "metadata": StringJSONDatabaseField(
            name="metadata", nullable=True, description="JSON metadata about the release."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the release was recorded."),
    },
)

error_tracking_symbol_sets: PostgresTable = PostgresTable(
    name="error_tracking_symbol_sets",
    postgres_table_name="posthog_errortrackingsymbolset",
    access_scope="error_tracking",
    description="Symbol sets (source maps / debug symbols) used to symbolicate stack traces; one row per symbol set.",
    fields={
        "id": StringDatabaseField(name="id", description="Symbol set UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "ref": StringDatabaseField(
            name="ref", description="Reference identifying the symbol set, e.g. a chunk/file id."
        ),
        "release_id": StringDatabaseField(
            name="release_id",
            nullable=True,
            description="Release this symbol set belongs to; joins to error_tracking_releases.id.",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the symbol set was uploaded."),
        "last_used": DateTimeDatabaseField(
            name="last_used", nullable=True, description="When the symbol set was last used to symbolicate."
        ),
        "failure_reason": StringDatabaseField(
            name="failure_reason", nullable=True, description="Why symbolication with this set failed, if applicable."
        ),
    },
)

logs_views: PostgresTable = PostgresTable(
    name="logs_views",
    postgres_table_name="logs_logsview",
    access_scope="logs",
    description="Saved log explorer views (saved filter sets for logs); one row per saved view.",
    fields={
        "id": StringDatabaseField(name="id", description="View UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "short_id": StringDatabaseField(name="short_id", description="Short URL-safe id used in view links."),
        "name": StringDatabaseField(name="name", description="View name."),
        "filters": StringJSONDatabaseField(name="filters", description="JSON log filters defining the view."),
        "_pinned": BooleanDatabaseField(name="pinned", hidden=True),
        "pinned": ExpressionField(
            name="pinned",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_pinned"])]),
            description="1 if the view is pinned, 0 otherwise.",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the view was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the view was last updated."),
    },
)

logs_alerts: PostgresTable = PostgresTable(
    name="logs_alerts",
    postgres_table_name="logs_logsalertconfiguration",
    access_scope="logs",
    description="Alerts that fire when matching log volume crosses a threshold; one row per logs alert.",
    fields={
        "id": StringDatabaseField(name="id", description="Alert UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Alert name."),
        "_enabled": BooleanDatabaseField(name="enabled", hidden=True),
        "enabled": ExpressionField(
            name="enabled",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_enabled"])]),
            description="1 if the alert is enabled, 0 otherwise.",
        ),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON log filters defining which logs the alert counts."
        ),
        "threshold_count": IntegerDatabaseField(
            name="threshold_count", description="Log count threshold that triggers the alert."
        ),
        "threshold_operator": StringDatabaseField(
            name="threshold_operator", description="Comparison against the threshold, e.g. '>', '>='."
        ),
        "window_minutes": IntegerDatabaseField(
            name="window_minutes", description="Length of the evaluation window, in minutes."
        ),
        "check_interval_minutes": IntegerDatabaseField(
            name="check_interval_minutes", description="How often the alert is evaluated, in minutes."
        ),
        "state": StringDatabaseField(name="state", description="Current alert state, e.g. 'firing' or 'not_firing'."),
        "evaluation_periods": IntegerDatabaseField(
            name="evaluation_periods", description="Number of consecutive periods evaluated together."
        ),
        "datapoints_to_alarm": IntegerDatabaseField(
            name="datapoints_to_alarm", description="How many periods must breach before alarming."
        ),
        "cooldown_minutes": IntegerDatabaseField(
            name="cooldown_minutes", description="Minimum minutes between notifications."
        ),
        "snooze_until": DateTimeDatabaseField(
            name="snooze_until", nullable=True, description="Alert is snoozed until this time."
        ),
        "next_check_at": DateTimeDatabaseField(
            name="next_check_at", nullable=True, description="When the alert is next scheduled to be evaluated."
        ),
        "last_notified_at": DateTimeDatabaseField(
            name="last_notified_at", nullable=True, description="When a notification was last sent."
        ),
        "last_checked_at": DateTimeDatabaseField(
            name="last_checked_at", nullable=True, description="When the alert was last evaluated."
        ),
        "consecutive_failures": IntegerDatabaseField(
            name="consecutive_failures", description="Number of consecutive evaluation failures."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the alert was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the alert was last updated."),
    },
)

support_tickets: PostgresTable = PostgresTable(
    name="support_tickets",
    postgres_table_name="posthog_conversations_ticket",
    access_scope="ticket",
    description="Customer support tickets/conversations; one row per ticket, with channel, status, and message counts.",
    fields={
        "id": StringDatabaseField(name="id", description="Ticket UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "ticket_number": IntegerDatabaseField(
            name="ticket_number", description="Human-friendly sequential ticket number."
        ),
        "channel_source": StringDatabaseField(
            name="channel_source", description="Channel the ticket came in on, e.g. 'email', 'widget'."
        ),
        "channel_detail": StringDatabaseField(
            name="channel_detail", nullable=True, description="Additional channel detail, e.g. inbox or address."
        ),
        "distinct_id": StringDatabaseField(
            name="distinct_id", description="Distinct id of the person who opened the ticket."
        ),
        "status": StringDatabaseField(name="status", description="Ticket status, e.g. 'open', 'pending', 'closed'."),
        "priority": StringDatabaseField(
            name="priority", nullable=True, description="Ticket priority, e.g. 'low', 'high'."
        ),
        "anonymous_traits": StringJSONDatabaseField(
            name="anonymous_traits", description="JSON traits captured for an anonymous requester."
        ),
        "_ai_resolved": BooleanDatabaseField(name="ai_resolved", hidden=True),
        "ai_resolved": ExpressionField(
            name="ai_resolved",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_ai_resolved"])]),
            description="1 if the ticket was resolved by AI without human escalation, 0 otherwise.",
        ),
        "escalation_reason": StringDatabaseField(
            name="escalation_reason", nullable=True, description="Why the ticket was escalated to a human, if it was."
        ),
        "message_count": IntegerDatabaseField(
            name="message_count", description="Total number of messages in the ticket."
        ),
        "unread_customer_count": IntegerDatabaseField(
            name="unread_customer_count", description="Messages unread by the customer."
        ),
        "unread_team_count": IntegerDatabaseField(
            name="unread_team_count", description="Messages unread by the support team."
        ),
        "last_message_at": DateTimeDatabaseField(
            name="last_message_at", nullable=True, description="When the most recent message was sent."
        ),
        "last_message_text": StringDatabaseField(
            name="last_message_text", nullable=True, description="Text of the most recent message."
        ),
        "email_subject": StringDatabaseField(
            name="email_subject", nullable=True, description="Subject line for email-channel tickets."
        ),
        "email_from": StringDatabaseField(
            name="email_from", nullable=True, description="Sender address for email-channel tickets."
        ),
        "session_id": StringDatabaseField(
            name="session_id", nullable=True, description="Session recording id associated with the ticket, if any."
        ),
        "session_context": StringJSONDatabaseField(
            name="session_context", description="JSON context captured from the user's session."
        ),
        "sla_due_at": DateTimeDatabaseField(
            name="sla_due_at",
            nullable=True,
            description="When the ticket's SLA response is due; a past value on an unresolved ticket means the SLA is currently breached.",
        ),
        "snoozed_until": DateTimeDatabaseField(
            name="snoozed_until", nullable=True, description="When a snoozed ticket automatically reopens, if snoozed."
        ),
        "organization_id": StringDatabaseField(
            name="organization_id",
            nullable=True,
            description="External organization/account identifier the requester belongs to, if known.",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the ticket was opened."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the ticket was last updated."),
    },
)

support_ticket_messages: PostgresTable = PostgresTable(
    name="support_ticket_messages",
    postgres_table_name="posthog_comment",
    access_scope="ticket",
    # Ticket messages are stored as comments; only expose that scope, and mirror the API's deleted filter.
    predicates=[parse_expr("scope = 'conversations_ticket'"), parse_expr("ifNull(deleted, false) != true")],
    description="Messages on support tickets (customer messages, team and AI replies, private notes); one row per message.",
    fields={
        "id": StringDatabaseField(name="id", description="Message UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        # Backing columns for the table predicates; hidden because the filters make them constant.
        "scope": StringDatabaseField(name="scope", hidden=True),
        "deleted": BooleanDatabaseField(name="deleted", nullable=True, hidden=True),
        "ticket_id": StringDatabaseField(
            name="item_id", description="Ticket this message belongs to; joins to support_tickets.id."
        ),
        "content": StringDatabaseField(name="content", nullable=True, description="Message text."),
        "author_type": ExpressionField(
            name="author_type",
            expr=parse_expr("JSONExtractString(ifNull(item_context, '{}'), 'author_type')"),
            description="Who wrote the message: 'customer', 'support' (team member), or 'AI'.",
        ),
        "is_private": ExpressionField(
            name="is_private",
            expr=parse_expr("toInt(JSONExtractBool(ifNull(item_context, '{}'), 'is_private'))"),
            description="1 for private internal notes not visible to the customer, 0 for customer-visible messages.",
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id",
            nullable=True,
            description="Team member who wrote the message; NULL for customer or AI messages.",
        ),
        "item_context": StringJSONDatabaseField(
            name="item_context",
            nullable=True,
            description="JSON message metadata (author type, privacy, delivery status).",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the message was sent."),
    },
)

review_queues: PostgresTable = PostgresTable(
    name="review_queues",
    postgres_table_name="llm_analytics_reviewqueue",
    access_scope="llm_analytics",
    description="AI observability review queues: named lists of traces queued for human review; one row per queue.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Queue UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Queue name."),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the queue."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the queue was created."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the queue was last updated."
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the queue has been deleted, 0 otherwise.",
        ),
        "deleted_at": DateTimeDatabaseField(
            name="deleted_at", nullable=True, description="When the queue was deleted; NULL if not deleted."
        ),
    },
)

review_queue_items: PostgresTable = PostgresTable(
    name="review_queue_items",
    postgres_table_name="llm_analytics_reviewqueueitem",
    access_scope="llm_analytics",
    description="Individual LLM traces queued in a review queue; one row per queued trace.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Queue item UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "queue_id": UUIDDatabaseField(
            name="queue_id", description="Queue this item belongs to; joins to review_queues.id."
        ),
        "trace_id": StringDatabaseField(name="trace_id", description="LLM trace queued for review."),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who added the item to the queue."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the item was queued."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the item was last updated."
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the item has been deleted, 0 otherwise.",
        ),
        "deleted_at": DateTimeDatabaseField(
            name="deleted_at", nullable=True, description="When the item was deleted; NULL if not deleted."
        ),
    },
)

trace_reviews: PostgresTable = PostgresTable(
    name="trace_reviews",
    postgres_table_name="llm_analytics_tracereview",
    access_scope="llm_analytics",
    description="Human reviews of LLM traces; one row per review, with scores attached in trace_review_scores.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Review UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "trace_id": StringDatabaseField(name="trace_id", description="LLM trace that was reviewed."),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the review record."
        ),
        "reviewed_by_id": IntegerDatabaseField(
            name="reviewed_by_id", nullable=True, description="User who performed the review."
        ),
        "comment": StringDatabaseField(name="comment", nullable=True, description="Reviewer's free-text comment."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the review was created."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the review was last updated."
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the review has been deleted, 0 otherwise.",
        ),
        "deleted_at": DateTimeDatabaseField(
            name="deleted_at", nullable=True, description="When the review was deleted; NULL if not deleted."
        ),
    },
)

trace_review_scores: PostgresTable = PostgresTable(
    name="trace_review_scores",
    postgres_table_name="llm_analytics_tracereviewscore",
    access_scope="llm_analytics",
    # Child of trace_review: object-level access control applies to the parent review, not the score's own id.
    access_control_id_field="review_id",
    description="Scores recorded against a trace review for a given score definition; one row per (review, score) pair.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Score UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "review_id": UUIDDatabaseField(
            name="review_id", description="Review this score belongs to; joins to trace_reviews.id."
        ),
        "definition_id": UUIDDatabaseField(
            name="definition_id", description="Score definition scored against; joins to score_definitions.id."
        ),
        "definition_version": UUIDDatabaseField(
            name="definition_version", description="Specific version of the score definition used."
        ),
        "definition_version_number": IntegerDatabaseField(
            name="definition_version_number", description="Numeric version of the score definition used."
        ),
        "definition_config": StringJSONDatabaseField(
            name="definition_config", description="JSON snapshot of the definition config at scoring time."
        ),
        "categorical_values": StringArrayDatabaseField(
            name="categorical_values",
            nullable=True,
            description="Selected category values, for categorical score kinds.",
        ),
        "numeric_value": DecimalDatabaseField(
            name="numeric_value", nullable=True, description="Recorded value, for numeric score kinds."
        ),
        "boolean_value": BooleanDatabaseField(
            name="boolean_value", nullable=True, description="Recorded value, for boolean score kinds."
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who recorded the score."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the score was recorded."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the score was last updated."
        ),
    },
)

score_definitions: PostgresTable = PostgresTable(
    name="score_definitions",
    postgres_table_name="llm_analytics_scoredefinition",
    access_scope="llm_analytics",
    description="Definitions of scores/metrics used when reviewing LLM traces; one row per score definition.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Score definition UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Score definition name."),
        "description": StringDatabaseField(name="description", description="What the score measures."),
        "kind": StringDatabaseField(
            name="kind", description="Score value type, e.g. 'categorical', 'numeric', 'boolean'."
        ),
        "archived": BooleanDatabaseField(name="archived", description="Whether the definition is archived."),
        "current_version_id": UUIDDatabaseField(
            name="current_version_id", nullable=True, description="Currently active version of this definition."
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the definition."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the definition was created."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the definition was last updated."
        ),
    },
)

early_access_features: PostgresTable = PostgresTable(
    name="early_access_features",
    postgres_table_name="posthog_earlyaccessfeature",
    access_scope="early_access_feature",
    description="Early access features users can opt into; one row per feature, backed by a feature flag.",
    fields={
        "id": StringDatabaseField(name="id", description="Early access feature UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "feature_flag_id": IntegerDatabaseField(
            name="feature_flag_id", description="Feature flag gating the feature; joins to feature_flags.id."
        ),
        "name": StringDatabaseField(name="name", description="Feature name shown to users."),
        "description": StringDatabaseField(name="description", description="Feature description shown to users."),
        "stage": StringDatabaseField(
            name="stage", description="Lifecycle stage, e.g. 'concept', 'beta', 'general-availability'."
        ),
        "documentation_url": StringDatabaseField(
            name="documentation_url", description="Link to the feature's documentation."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the feature was created."),
    },
)

usage_metrics: PostgresTable = PostgresTable(
    name="usage_metrics",
    postgres_table_name="posthog_groupusagemetric",
    access_scope="usage_metric",
    description="Per-group usage metric definitions shown on group dashboards; one row per metric.",
    fields={
        "id": StringDatabaseField(name="id", description="Usage metric UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "group_type_index": IntegerDatabaseField(
            name="group_type_index", description="Group type the metric applies to (0-4)."
        ),
        "name": StringDatabaseField(name="name", description="Metric name."),
        "format": StringDatabaseField(
            name="format", description="Display format, e.g. 'numeric', 'currency', 'percentage'."
        ),
        "interval": IntegerDatabaseField(
            name="interval", description="Rolling window length, in days, the metric is computed over."
        ),
        "display": StringDatabaseField(
            name="display", description="How the metric is visualized, e.g. 'number' or 'sparkline'."
        ),
        "filters": StringJSONDatabaseField(
            name="filters", description="JSON event filters defining what the metric counts."
        ),
        "math": StringDatabaseField(name="math", description="Aggregation applied, e.g. 'total', 'unique', 'sum'."),
        "math_property": StringDatabaseField(
            name="math_property",
            nullable=True,
            description="Property aggregated when math is property-based, e.g. sum.",
        ),
    },
)


tasks: PostgresTable = PostgresTable(
    name="tasks",
    postgres_table_name="posthog_task",
    access_scope="task",
    # Mirror the REST API's default filter: internal tasks (signals pipeline, etc.) are not
    # exposed to end users. They are excluded entirely from HogQL.
    predicates=[parse_expr("internal != true")],
    description="Tasks (PostHog Code / agent work items); one row per user-facing task (internal pipeline tasks are excluded).",
    fields={
        "id": StringDatabaseField(name="id", description="Task UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the task."
        ),
        "github_integration_id": IntegerDatabaseField(
            name="github_integration_id",
            nullable=True,
            description="GitHub integration used for the task; joins to integrations.id.",
        ),
        "task_number": IntegerDatabaseField(
            name="task_number", nullable=True, description="Human-friendly sequential task number."
        ),
        "title": StringDatabaseField(name="title", description="Task title."),
        "_title_manually_set": BooleanDatabaseField(name="title_manually_set", hidden=True),
        "title_manually_set": ExpressionField(
            name="title_manually_set",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_title_manually_set"])]),
            description="1 if the title was set by a user rather than auto-generated, 0 otherwise.",
        ),
        "description": StringDatabaseField(name="description", description="Task description/prompt."),
        "origin_product": StringDatabaseField(name="origin_product", description="Product the task originated from."),
        "repository": StringDatabaseField(
            name="repository", nullable=True, description="Target repository, e.g. 'owner/repo'."
        ),
        "json_schema": StringJSONDatabaseField(
            name="json_schema", nullable=True, description="JSON schema describing structured task inputs/outputs."
        ),
        "_internal": BooleanDatabaseField(name="internal", hidden=True),
        "internal": ExpressionField(
            name="internal",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_internal"])]),
            description="1 for internal pipeline tasks, 0 for user tasks (always 0 here due to the table filter).",
        ),
        "_deleted": BooleanDatabaseField(name="deleted", hidden=True),
        "deleted": ExpressionField(
            name="deleted",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_deleted"])]),
            description="1 if the task has been deleted, 0 otherwise.",
        ),
        "deleted_at": DateTimeDatabaseField(
            name="deleted_at", nullable=True, description="When the task was deleted; NULL if not deleted."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the task was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the task was last updated."),
    },
)

task_runs: PostgresTable = PostgresTable(
    name="task_runs",
    postgres_table_name="posthog_task_run",
    access_scope="task",
    description="Execution runs of a task; one row per run attempt, with status and outputs.",
    fields={
        "id": StringDatabaseField(name="id", description="Task run UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "task_id": StringDatabaseField(name="task_id", description="Task this run belongs to; joins to tasks.id."),
        "branch": StringDatabaseField(name="branch", nullable=True, description="Git branch the run worked on."),
        "environment": StringDatabaseField(name="environment", description="Environment the run executed in."),
        "stage": StringDatabaseField(name="stage", nullable=True, description="Current workflow stage of the run."),
        "status": StringDatabaseField(name="status", description="Run status, e.g. Running, Completed, Failed."),
        "error_message": StringDatabaseField(
            name="error_message", nullable=True, description="Error message if the run failed."
        ),
        "output": StringJSONDatabaseField(
            name="output", nullable=True, description="JSON structured output produced by the run."
        ),
        "artifacts": StringJSONDatabaseField(
            name="artifacts", description="JSON references to artifacts produced (PRs, files, etc.)."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the run started."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the run row was last updated."),
        "completed_at": DateTimeDatabaseField(
            name="completed_at", nullable=True, description="When the run finished; NULL while running."
        ),
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
    description="Sandbox environments that task runs execute in (network policy, allowed repos); one row per shared environment (private and internal environments are excluded).",
    fields={
        "id": StringDatabaseField(name="id", description="Sandbox environment UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the environment."
        ),
        "name": StringDatabaseField(name="name", description="Environment name."),
        "network_access_level": StringDatabaseField(
            name="network_access_level", description="Network egress policy, e.g. 'none', 'restricted', 'full'."
        ),
        "allowed_domains": StringArrayDatabaseField(
            name="allowed_domains", description="Domains the sandbox may reach when egress is restricted."
        ),
        "_include_default_domains": BooleanDatabaseField(name="include_default_domains", hidden=True),
        "include_default_domains": ExpressionField(
            name="include_default_domains",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_include_default_domains"])]),
            description="1 if the platform default allow-list is merged with allowed_domains, 0 otherwise.",
        ),
        "repositories": StringArrayDatabaseField(
            name="repositories", description="Repositories the environment may check out."
        ),
        "_private": BooleanDatabaseField(name="private", hidden=True),
        "private": ExpressionField(
            name="private",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_private"])]),
            description="1 if private to its creator, 0 if shared (always 0 here due to the table filter).",
        ),
        "_internal": BooleanDatabaseField(name="internal", hidden=True),
        "internal": ExpressionField(
            name="internal",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_internal"])]),
            description="1 for internal environments, 0 for user environments (always 0 here due to the table filter).",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the environment was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the environment was last updated."),
    },
)

business_knowledge_sources: PostgresTable = PostgresTable(
    name="business_knowledge_sources",
    postgres_table_name="posthog_business_knowledge_knowledgesource",
    access_scope="business_knowledge",
    description="Sources of business knowledge ingested for AI context (uploaded files, crawled URLs); one row per source.",
    fields={
        "id": StringDatabaseField(name="id", description="Source UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Source name."),
        "source_type": StringDatabaseField(name="source_type", description="Source type, e.g. 'file' or 'url'."),
        "status": StringDatabaseField(
            name="status", description="Ingestion status, e.g. 'pending', 'processing', 'completed', 'failed'."
        ),
        "error_message": StringDatabaseField(name="error_message", description="Error message if ingestion failed."),
        "source_url": StringDatabaseField(name="source_url", description="URL crawled, for url-type sources."),
        "crawl_mode": StringDatabaseField(
            name="crawl_mode", description="Crawl strategy for url sources, e.g. single page vs site."
        ),
        "original_filename": StringDatabaseField(
            name="original_filename", description="Uploaded file name, for file-type sources."
        ),
        "file_content_type": StringDatabaseField(
            name="file_content_type", description="MIME type of the uploaded file."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the source was added."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the source was last updated."),
    },
)

business_knowledge_documents: PostgresTable = PostgresTable(
    name="business_knowledge_documents",
    postgres_table_name="posthog_business_knowledge_knowledgedocument",
    access_scope="business_knowledge",
    description="Documents extracted from a business knowledge source (e.g. one page or file); one row per document.",
    fields={
        "id": StringDatabaseField(name="id", description="Document UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "source_id": StringDatabaseField(
            name="source_id", description="Source the document came from; joins to business_knowledge_sources.id."
        ),
        "stable_id": StringDatabaseField(
            name="stable_id", description="Stable identifier that survives re-ingestion of the same document."
        ),
        "title": StringDatabaseField(name="title", description="Document title."),
        "url": StringDatabaseField(name="url", description="URL the document was fetched from, if any."),
        "content_hash": StringDatabaseField(
            name="content_hash", description="Hash of the document content, used to detect changes."
        ),
        "tombstoned_at": DateTimeDatabaseField(
            name="tombstoned_at",
            nullable=True,
            description="When the document was tombstoned (removed from source); NULL if live.",
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the document was first ingested."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the document was last updated."),
    },
)

business_knowledge_chunks: PostgresTable = PostgresTable(
    name="business_knowledge_chunks",
    postgres_table_name="posthog_business_knowledge_knowledgechunk",
    access_scope="business_knowledge",
    description="Chunks a knowledge document is split into for embedding/retrieval; one row per chunk.",
    fields={
        "id": StringDatabaseField(name="id", description="Chunk UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "source_id": StringDatabaseField(
            name="source_id", description="Source the chunk belongs to; joins to business_knowledge_sources.id."
        ),
        "document_id": StringDatabaseField(
            name="document_id", description="Document the chunk belongs to; joins to business_knowledge_documents.id."
        ),
        "heading_path": StringDatabaseField(
            name="heading_path", description="Breadcrumb of headings locating the chunk within the document."
        ),
        "ordinal": IntegerDatabaseField(
            name="ordinal", description="0-based position of the chunk within its document."
        ),
        "content": StringDatabaseField(name="content", description="Text content of the chunk."),
        "char_count": IntegerDatabaseField(name="char_count", description="Number of characters in the chunk."),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the chunk was created."),
    },
)


tags: PostgresTable = PostgresTable(
    name="tags",
    postgres_table_name="posthog_tag",
    description="Tags that can be attached to taggable objects (insights, dashboards, etc.); one row per tag.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Tag UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Tag text."),
    },
)


class SystemTables(TableNode):
    name: str = "system"
    children: dict[str, TableNode] = {
        "accounts": TableNode(name="accounts", table=accounts),
        "_account_tagged_items": TableNode(name="_account_tagged_items", table=account_tagged_items, hidden=True),
        "_account_resource_notebooks": TableNode(
            name="_account_resource_notebooks", table=account_resource_notebooks, hidden=True
        ),
        "_account_custom_property_values": TableNode(
            name="_account_custom_property_values", table=account_custom_property_values, hidden=True
        ),
        "account_relationship_definitions": TableNode(
            name="account_relationship_definitions", table=account_relationship_definitions
        ),
        "account_relationships": TableNode(name="account_relationships", table=account_relationships),
        "activity_logs": TableNode(name="activity_logs", table=activity_logs),
        "actions": TableNode(name="actions", table=actions),
        "alerts": TableNode(name="alerts", table=alerts),
        "annotations": TableNode(name="annotations", table=annotations),
        "batch_export_backfills": TableNode(name="batch_export_backfills", table=batch_export_backfills),
        "batch_exports": TableNode(name="batch_exports", table=batch_exports),
        "business_knowledge_chunks": TableNode(name="business_knowledge_chunks", table=business_knowledge_chunks),
        "business_knowledge_documents": TableNode(
            name="business_knowledge_documents", table=business_knowledge_documents
        ),
        "business_knowledge_sources": TableNode(name="business_knowledge_sources", table=business_knowledge_sources),
        "cohort_calculation_history": TableNode(name="cohort_calculation_history", table=cohort_calculation_history),
        "cohorts": TableNode(name="cohorts", table=cohorts),
        "custom_property_definitions": TableNode(name="custom_property_definitions", table=custom_property_definitions),
        "dashboards": TableNode(name="dashboards", table=dashboards),
        "dashboard_tiles": TableNode(name="dashboard_tiles", table=dashboard_tiles),
        "data_modeling_jobs": TableNode(name="data_modeling_jobs", table=data_modeling_jobs),
        "data_modeling_views": TableNode(name="data_modeling_views", table=data_modeling_views),
        "data_modeling_endpoint_versions": TableNode(name="data_modeling_endpoint_versions", table=endpoint_versions),
        "data_modeling_endpoints": TableNode(name="data_modeling_endpoints", table=endpoints),
        "data_warehouse_sources": TableNode(name="data_warehouse_sources", table=data_warehouse_sources),
        "data_warehouse_tables": TableNode(name="data_warehouse_tables", table=data_warehouse_tables),
        "error_tracking_assignment_rules": TableNode(
            name="error_tracking_assignment_rules", table=error_tracking_assignment_rules
        ),
        "error_tracking_bypass_rules": TableNode(name="error_tracking_bypass_rules", table=error_tracking_bypass_rules),
        "error_tracking_issue_assignments": TableNode(
            name="error_tracking_issue_assignments", table=error_tracking_issue_assignments
        ),
        "error_tracking_issue_fingerprints": TableNode(
            name="error_tracking_issue_fingerprints", table=error_tracking_issue_fingerprints
        ),
        "error_tracking_issues": TableNode(name="error_tracking_issues", table=error_tracking_issues),
        "error_tracking_releases": TableNode(name="error_tracking_releases", table=error_tracking_releases),
        "error_tracking_symbol_sets": TableNode(name="error_tracking_symbol_sets", table=error_tracking_symbol_sets),
        "error_tracking_suppression_rules": TableNode(
            name="error_tracking_suppression_rules", table=error_tracking_suppression_rules
        ),
        "early_access_features": TableNode(name="early_access_features", table=early_access_features),
        "experiments": TableNode(name="experiments", table=experiments),
        "exports": TableNode(name="exports", table=exports),
        "feature_flags": TableNode(name="feature_flags", table=feature_flags),
        "file_system": TableNode(name="file_system", table=file_system),
        "groups": TableNode(name="groups", table=groups),
        "group_type_mappings": TableNode(name="group_type_mappings", table=group_type_mappings),
        "information_schema": information_schema_node(),
        "hog_flows": TableNode(name="hog_flows", table=hog_flows),
        "hog_functions": TableNode(name="hog_functions", table=hog_functions),
        "ingestion_warnings": TableNode(name="ingestion_warnings", table=IngestionWarningsTable()),
        "integrations": TableNode(name="integrations", table=integrations),
        "integration_repository_cache": TableNode(
            name="integration_repository_cache", table=integration_repository_cache
        ),
        "insight_variables": TableNode(name="insight_variables", table=insight_variables),
        "logs_alerts": TableNode(name="logs_alerts", table=logs_alerts),
        "logs_views": TableNode(name="logs_views", table=logs_views),
        "insights": TableNode(name="insights", table=insights),
        "notebooks": TableNode(name="notebooks", table=notebooks),
        "sandbox_environments": TableNode(name="sandbox_environments", table=sandbox_environments),
        "review_queue_items": TableNode(name="review_queue_items", table=review_queue_items),
        "review_queues": TableNode(name="review_queues", table=review_queues),
        "score_definitions": TableNode(name="score_definitions", table=score_definitions),
        "session_recording_playlists": TableNode(name="session_recording_playlists", table=session_recording_playlists),
        "session_recordings": TableNode(name="session_recordings", table=session_recordings),
        "source_schemas": TableNode(name="source_schemas", table=source_schemas),
        "source_sync_jobs": TableNode(name="source_sync_jobs", table=source_sync_jobs),
        "support_ticket_messages": TableNode(name="support_ticket_messages", table=support_ticket_messages),
        "support_tickets": TableNode(name="support_tickets", table=support_tickets),
        "surveys": TableNode(name="surveys", table=surveys),
        "task_runs": TableNode(name="task_runs", table=task_runs),
        "tags": TableNode(name="tags", table=tags),
        "tasks": TableNode(name="tasks", table=tasks),
        "teams": TableNode(name="teams", table=teams),
        "trace_review_scores": TableNode(name="trace_review_scores", table=trace_review_scores),
        "trace_reviews": TableNode(name="trace_reviews", table=trace_reviews),
        "usage_metrics": TableNode(name="usage_metrics", table=usage_metrics),
    }


@lru_cache(maxsize=1)
def access_controlled_system_tables() -> dict[str, APIScopeObject]:
    """Access-controlled system tables as {table_name: resource}, e.g. {"notebooks": "notebook"}.
    SystemTables().children is static, so this is computed once and reused."""
    return {
        name: node.table.access_scope
        for name, node in SystemTables().children.items()
        if isinstance(node.table, PostgresTable) and node.table.access_scope is not None
    }
