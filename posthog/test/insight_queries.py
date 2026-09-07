"""Build the `query` payloads that tests send when they write an insight.

The insights API only stores a definition sent as a query, so a test that wants an insight with a
given definition writes that query itself.
"""

from typing import Any

from posthog.schema_migrations.upgrade import upgrade


def insight_query(source: dict[str, Any]) -> dict[str, Any]:
    """Wrap a query source in the node an insight stores, at the current schema version.

    `source` only needs the fields the test reads. The version has to be current: a stored query one
    version behind is upgraded on read, so the next write logs a query change the caller never made.
    """
    return upgrade({"kind": "InsightVizNode", "source": source, "full": True})


def default_pageview_query() -> dict[str, Any]:
    # The shape the frontend writes for a fresh trends insight (`getTrendsQueryDefault`): a series, an
    # empty `trendsFilter`, and no breakdown. `trendsFilter: {}` is not the same query as no
    # `trendsFilter` at all, which resolves to null.
    return insight_query(
        {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "total"}],
            "trendsFilter": {},
        }
    )
