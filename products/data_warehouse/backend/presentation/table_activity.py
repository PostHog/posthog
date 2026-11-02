"""Activity log rows for the edits a person makes to a warehouse table.

The table model does not carry ``ModelActivityMixin``. Every sync saves the table, and the mixin
reads the row before each save through a manager that adds two joins and a prefetch. The API
write paths call ``log_table_activity`` instead.
"""

from typing import TYPE_CHECKING, Any, Literal

from posthog.models.activity_logging.activity_log import Change, Detail, dict_changes_between, log_activity
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated

if TYPE_CHECKING:
    from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def snapshot_table(table: "DataWarehouseTable") -> dict[str, Any]:
    """The user-editable state of a table, taken before an edit so the log can show the diff."""
    return {
        "name": table.name,
        "format": table.format,
        "url_pattern": table.url_pattern,
        "deleted": bool(table.deleted),
        "options": dict(table.options or {}),
        # A background task rewrites the `valid` flag of each column, so only the type is compared.
        "columns": {
            name: column.get("clickhouse") if isinstance(column, dict) else column
            for name, column in (table.columns or {}).items()
        },
    }


def log_table_activity(
    table: "DataWarehouseTable",
    activity: Literal["created", "updated", "deleted"],
    *,
    before: dict[str, Any] | None = None,
    credential_changed: bool = False,
    force_save: bool = False,
) -> None:
    diff = dict_changes_between("DataWarehouseTable", before, snapshot_table(table)) if before is not None else []
    if any(change.field == "deleted" and change.after for change in diff):
        activity = "deleted"
    # Any activity-log reader sees this row, including readers denied the table, so it records
    # which fields changed and never their values.
    changes = [
        Change(
            type="DataWarehouseTable",
            field=change.field,
            action=change.action,
            before="masked" if change.before is not None else None,
            after="masked" if change.after is not None else None,
        )
        for change in diff
        if change.field != "deleted"
    ]
    if credential_changed:
        changes.append(Change(type="DataWarehouseTable", field="credential", action="changed"))

    log_activity(
        organization_id=table.team.organization_id,
        team_id=table.team_id,
        user=get_current_user(),
        was_impersonated=get_was_impersonated(),
        item_id=table.id,
        scope="DataWarehouseTable",
        activity=activity,
        detail=Detail(name=table.name, changes=changes),
        force_save=force_save,
    )
