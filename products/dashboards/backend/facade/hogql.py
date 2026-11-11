"""HogQL surface for dashboards.

Exposed as `system.dashboards` and `system.dashboard_tiles`, so the SQL editor, insights and MCP can read
dashboards and their tiles, while every write still goes through the dashboards API.
"""

from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)
from posthog.hogql.database.postgres_table import PostgresTable

dashboards: PostgresTable = PostgresTable(
    name="dashboards",
    postgres_table_name="posthog_dashboard",
    access_scope="dashboard",
    access_control_creator_id_field="created_by_id",
    description="Dashboards: collections of insight tiles; one row per dashboard.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Dashboard id."),
        "team_id": IntegerDatabaseField(name="team_id", hidden=True),
        "name": StringDatabaseField(name="name", description="Dashboard name."),
        "description": StringDatabaseField(name="description", description="Dashboard description."),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the dashboard."
        ),
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
        "team_id": IntegerDatabaseField(name="team_id", hidden=True),
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
