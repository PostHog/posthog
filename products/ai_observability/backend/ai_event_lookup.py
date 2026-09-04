from datetime import datetime
from typing import Any

from posthog.clickhouse.client import query_with_columns
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.ai.ai_table_resolver import AIEventsExpiredError, AIEventsNotFoundError
from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES, HEAVY_COLUMN_TO_PROPERTY, merge_heavy_properties


def _query_ai_event(team_id: int, where_clauses: list[str], params: dict[str, object]) -> dict[str, Any] | None:
    """Read one event with its heavy AI columns from ai_events, or None when it is not there.

    An evaluation grades the heavy $ai_input / $ai_output, which live only on the
    dedicated ai_events table.
    """
    heavy_cols = ",\n                ".join(HEAVY_COLUMN_NAMES)
    # Tag these direct ClickHouse reads so the manual-eval-trigger lookup is attributed
    # to AI observability in query-usage analysis alongside the rest of the product.
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team_id):
        rows = query_with_columns(
            f"""
            SELECT
                uuid,
                event,
                properties,
                timestamp,
                team_id,
                distinct_id,
                person_id,
                {heavy_cols}
            FROM ai_events
            WHERE {" AND ".join(where_clauses)}
            LIMIT 1
            """,
            params,
            team_id=team_id,
        )
    if not rows:
        return None

    event_data = rows[0]
    # Merge heavy columns back into properties for the evaluation workflow.
    heavy_columns = {col: event_data.pop(col, "") for col in HEAVY_COLUMN_TO_PROPERTY}
    event_data["properties"] = merge_heavy_properties(event_data["properties"], heavy_columns)
    return event_data


def fetch_ai_event(team_id: int, where_clauses: list[str], params: dict[str, object]) -> dict[str, Any]:
    """Fetch the target event, and tell the two ways it can be absent apart.

    ai_events has a retention TTL, so when the event is missing we probe the long-lived events
    table purely to classify the miss. A stripped events row can't be evaluated either way.

    Raises AIEventsExpiredError if the event is gone from ai_events but still in events (aged
    past the TTL), or AIEventsNotFoundError if it is in neither.
    """
    event_data = _query_ai_event(team_id, where_clauses, params)
    if event_data is not None:
        return event_data

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team_id):
        exists_in_events = query_with_columns(
            f"""
            SELECT 1
            FROM events
            WHERE {" AND ".join(where_clauses)}
            LIMIT 1
            """,
            params,
            team_id=team_id,
        )
    if exists_in_events:
        raise AIEventsExpiredError("target event has aged past the ai_events retention window")
    raise AIEventsNotFoundError("target event not found")


def fetch_generation_event(
    team_id: int, event_uuid: str, timestamp: datetime | None = None, trace_id: str | None = None
) -> dict[str, Any] | None:
    """Look a generation up for a caller that holds no query filters beyond its identity.

    Returns None on a miss without the classification probe of `fetch_ai_event`: a backfill runs
    this once per unit, and a caller with only a uuid can do nothing different about an expired
    event than about a missing one.
    """
    where_clauses = ["team_id = %(team_id)s", "uuid = %(event_id)s"]
    params: dict[str, object] = {"team_id": team_id, "event_id": event_uuid.replace("-", "")}
    if trace_id is not None:
        # ai_events sorts on (team_id, trace_id, timestamp), so this is what turns the read into a
        # point lookup instead of a scan of every row the team has.
        where_clauses.append("trace_id = %(trace_id)s")
        params["trace_id"] = trace_id
    if timestamp is not None:
        # A day of slack each side covers the backdating a client SDK can apply between the
        # timestamp the caller recorded and the one the row carries.
        where_clauses.append("timestamp >= %(ts)s - INTERVAL 1 DAY")
        where_clauses.append("timestamp <= %(ts)s + INTERVAL 1 DAY")
        params["ts"] = timestamp
    return _query_ai_event(team_id, where_clauses, params)
