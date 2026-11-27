from __future__ import annotations

from typing import TYPE_CHECKING

from django.dispatch import receiver

from posthog.clickhouse.query_status import QueryNotFoundError, validate_completed_query_result

from products.canvas.backend.facade.contracts import CanvasResultAccess

if TYPE_CHECKING:
    from posthog.schema import QueryStatus


FILE_SYSTEM_RESULT_PREFIX = "file_system:"
FILE_SYSTEM_UNUSED = FILE_SYSTEM_RESULT_PREFIX + "unused"


def file_system_result_access(status: QueryStatus) -> CanvasResultAccess | None:
    if not status.complete or not isinstance(status.results, dict):
        return None
    for label in status.labels or []:
        if label.startswith(FILE_SYSTEM_RESULT_PREFIX):
            if label == FILE_SYSTEM_UNUSED:
                return None
            revision, separator, grants = label.removeprefix(FILE_SYSTEM_RESULT_PREFIX).partition(":")
            if not separator or not revision or not grants:
                raise QueryNotFoundError()
            return CanvasResultAccess(revision=revision, grants_digest=grants)
    # Old workers did not record dependencies. Table names are redacted from the
    # printed PostgreSQL call, so older federated HogQL results must be refreshed.
    if "hogql" in status.results:
        sql = status.results.get("clickhouse")
        if not isinstance(sql, str) or not sql or "postgresql(" in sql.lower():
            raise QueryNotFoundError()
    return None


@receiver(validate_completed_query_result)
def _validate_canvas_result_revision(sender: type, query_status: QueryStatus, **kwargs) -> None:
    if access := file_system_result_access(query_status):
        from products.canvas.backend.logic.visibility import canvas_visibility_revision  # noqa: PLC0415

        if access.revision != canvas_visibility_revision(query_status.team_id):
            raise QueryNotFoundError()
