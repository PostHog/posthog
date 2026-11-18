"""HogQL surface for annotations.

Exposed as `system.annotations`, so the SQL editor, insights and MCP can read annotations, while every
write still goes through the annotations API.
"""

from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    IntegerDatabaseField,
    StringDatabaseField,
)
from posthog.hogql.database.postgres_table import PostgresTable

annotations: PostgresTable = PostgresTable(
    name="annotations",
    postgres_table_name="posthog_annotation",
    access_scope="annotation",
    description="Annotations: dated notes overlaid on insight/dashboard charts; one row per annotation.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Annotation id."),
        "team_id": IntegerDatabaseField(name="team_id", hidden=True),
        "content": StringDatabaseField(name="content", nullable=True, description="Annotation text."),
        "scope": StringDatabaseField(
            name="scope",
            description="Where the annotation applies: 'project', 'organization', 'dashboard', 'dashboard_item' (insight), or 'recording'.",
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
