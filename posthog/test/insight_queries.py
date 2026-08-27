from typing import Any

from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.schema_migrations.upgrade import upgrade


def query_from_filters(filters: dict[str, Any]) -> dict[str, Any]:
    """The query a legacy `filters` payload converts to, ready to send to the insights API.

    The API stopped accepting `filters` on write, so a test that wants the insight those filters
    described sends this instead.

    `upgrade` stamps the current schema version. Without it the next save of the same insight
    rewrites the query to add the version, and the activity log reports that as a query change.
    """
    return upgrade(filter_to_query(filters).model_dump(exclude_none=True, mode="json"))
