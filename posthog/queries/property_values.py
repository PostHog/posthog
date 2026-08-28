from typing import Optional

from opentelemetry import trace

from posthog.models.team import Team
from posthog.queries.insight import insight_sync_execute

tracer = trace.get_tracer(__name__)


# property_values_distributed routes to the aggregated table on the aux cluster.
SELECT_EVENT_PROPERTY_VALUES_FROM_AGGREGATED_TABLE_SQL = """
SELECT DISTINCT property_value
FROM property_values_distributed
WHERE team_id = %(team_id)s
    AND property_type = 'event'
    AND property_key = %(key)s
    AND last_seen >= now() - INTERVAL 7 DAY
    {value_filter}
LIMIT 10
"""


def get_event_property_values_from_aggregated_table(key: str, team: Team, value: Optional[str] = None) -> list:
    with tracer.start_as_current_span("get_event_property_values_from_aggregated_table") as span:
        span.set_attribute("team_id", team.pk)
        span.set_attribute("property_key", key)
        span.set_attribute("has_value_filter", value is not None)

        params: dict = {"team_id": team.pk, "key": key}
        value_filter = ""
        if value:
            escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            value_filter = "AND lower(property_value) LIKE %(value)s"
            params["value"] = f"%{escaped.lower()}%"

        result = insight_sync_execute(
            SELECT_EVENT_PROPERTY_VALUES_FROM_AGGREGATED_TABLE_SQL.format(value_filter=value_filter),
            params,
            query_type="get_event_property_values_from_aggregated_table",
            team_id=team.pk,
        )
        span.set_attribute("result_count", len(result))
        return result
