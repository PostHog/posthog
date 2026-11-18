"""The read-access check a run or a cadence change makes on a saved query's sources."""

from rest_framework import exceptions

from posthog.hogql.database.database import Database

from posthog.models import User
from posthog.rbac.query_access import assert_user_can_read_sql

from ..models.datawarehouse_saved_query import DataWarehouseSavedQuery


def assert_user_can_read_saved_query(
    saved_query: DataWarehouseSavedQuery, user: User, *, database: Database | None = None
) -> None:
    """Raise PermissionDenied unless `user` can read everything the saved query selects from.

    The check reads `saved_query.sql`, which binds the incremental window start to NULL. The stored
    text leaves it unbound, and an unbound placeholder fails resolution as an unknown column.
    """
    query = saved_query.query
    if not isinstance(query, dict) or not isinstance(query.get("query"), str):
        raise exceptions.ValidationError("Query is missing.")
    assert_user_can_read_sql(saved_query.sql, saved_query.team_id, user, database=database)
