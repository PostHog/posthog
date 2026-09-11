from posthog.hogql.base import Expr
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    UUIDDatabaseField,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.parser import parse_expr


class _CustomerTasksTable(PostgresTable):
    def get_predicates(self, context: HogQLContext | None = None) -> list[Expr]:
        if context is None or context.database is None or not context.database.has_table("system.accounts"):
            return [parse_expr("account_id IS NULL")]
        return super().get_predicates(context)


customer_tasks = _CustomerTasksTable(
    name="customer_tasks",
    postgres_table_name="customer_analytics_customertask",
    access_scope="customer_task",
    access_control_creator_id_field="created_by_id",
    predicates=[parse_expr("account_id IS NULL OR account_id IN (SELECT id FROM system.accounts)")],
    description="Customer analytics tasks visible to the caller. Includes archived tasks; filter archived_at IS NULL for active tasks.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Task UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "account_id": UUIDDatabaseField(name="account_id", nullable=True, description="Linked account UUID, if any."),
        "name": StringDatabaseField(name="name", description="Task name."),
        "description": StringDatabaseField(name="description", nullable=True, description="Task description."),
        "status": StringDatabaseField(name="status", description="open, in_progress, completed, or canceled."),
        "assigned_to_id": IntegerDatabaseField(
            name="assigned_to_id", nullable=True, description="Assigned PostHog user ID."
        ),
        "due_at": DateTimeDatabaseField(name="due_at", nullable=True, description="Task deadline."),
        "completed_at": DateTimeDatabaseField(name="completed_at", nullable=True, description="Completion time."),
        "completed_by_id": IntegerDatabaseField(
            name="completed_by_id", nullable=True, description="User credited with completion."
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the task."
        ),
        "archived_at": DateTimeDatabaseField(
            name="archived_at", nullable=True, description="Archive time, or NULL while active."
        ),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "updated_at": DateTimeDatabaseField(name="updated_at"),
    },
)
