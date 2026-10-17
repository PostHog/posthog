"""Activity log rows for the edits a person makes to a warehouse table.

The table model does not carry ``ModelActivityMixin``. Every sync saves the table, and the mixin
reads the row before each save through a manager that adds two joins and a prefetch. The API
write paths call ``log_table_activity`` instead.
"""

import hashlib
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from posthog.models.activity_logging.activity_log import Change, Detail, dict_changes_between, log_activity
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated

if TYPE_CHECKING:
    from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def _redact_url(url: str) -> str:
    # A URL can carry an access key in its userinfo or a signature in its query string. The activity
    # row and its internal event must not copy either. A short digest keeps a query-only change visible.
    parts = urlsplit(url)
    host = parts.netloc.rsplit("@", 1)[-1]
    query = f"<redacted:{hashlib.sha256(parts.query.encode()).hexdigest()[:8]}>" if parts.query else ""
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def snapshot_table(table: "DataWarehouseTable") -> dict[str, Any]:
    """The user-editable state of a table, taken before an edit so the log can show the diff."""
    return {
        "name": table.name,
        "format": table.format,
        "url_pattern": _redact_url(table.url_pattern or ""),
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
    changes = dict_changes_between("DataWarehouseTable", before, snapshot_table(table)) if before is not None else []
    if credential_changed:
        # The values are secrets. The row records only that they changed.
        changes.append(Change(type="DataWarehouseTable", field="credential", action="changed"))
    if any(change.field == "deleted" and change.after for change in changes):
        activity = "deleted"

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
