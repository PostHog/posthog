"""Build the insight `query` payloads that tests used to write as legacy `filters`.

The insights API only stores a definition sent as a query, so a test that wants an insight with
a given definition sends the equivalent query instead.
"""

from typing import Any

from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.schema_migrations.upgrade import upgrade


def query_from_legacy_filters(filters: dict[str, Any]) -> dict[str, Any]:
    # Upgraded to the current schema version, which is the shape a read of the insight settles on.
    # Writing an older shape makes the next write log a query change the caller never made.
    return upgrade(
        {
            "kind": "InsightVizNode",
            "source": filter_to_query(filters).model_dump(exclude_none=True),
            "full": True,
        }
    )


def default_pageview_query() -> dict[str, Any]:
    return query_from_legacy_filters({"events": [{"id": "$pageview"}]})
