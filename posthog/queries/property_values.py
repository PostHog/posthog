from typing import Optional

from opentelemetry import trace

from posthog.models.person.sql import SELECT_PERSON_PROP_VALUES_SQL, SELECT_PERSON_PROP_VALUES_SQL_WITH_FILTER
from posthog.models.property.util import get_property_string_expr
from posthog.models.team import Team
from posthog.queries.insight import insight_sync_execute

tracer = trace.get_tracer(__name__)


def get_person_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    with tracer.start_as_current_span("get_person_property_values_for_key") as span:
        span.set_attribute("team_id", team.pk)
        span.set_attribute("property_key", key)
        span.set_attribute("has_value_filter", value is not None)

        if key == "distinct_id":
            result = _get_distinct_id_values(team, value)
            span.set_attribute("result_count", len(result))
            return result

        property_field, _ = get_property_string_expr("person", key, "%(key)s", "properties")

        if value:
            escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            result = insight_sync_execute(
                SELECT_PERSON_PROP_VALUES_SQL_WITH_FILTER.format(property_field=property_field),
                {"team_id": team.pk, "key": key, "value": "%{}%".format(escaped)},
                query_type="get_person_property_values_with_value",
                team_id=team.pk,
            )
        else:
            result = insight_sync_execute(
                SELECT_PERSON_PROP_VALUES_SQL.format(property_field=property_field),
                {"team_id": team.pk, "key": key},
                query_type="get_person_property_values",
                team_id=team.pk,
            )
        span.set_attribute("result_count", len(result))
        return result


# distinct_id lives in person_distinct_id2, not in person.properties — so the generic
# SELECT_PERSON_PROP_VALUES_SQL path would always return an empty list. We query the
# distinct-id table directly and let argMax hide tombstoned rows. The count is always 1
# per distinct_id since GROUP BY already deduplicates.
_SELECT_DISTINCT_IDS_SQL = """
SELECT distinct_id AS value, 1 AS c
FROM person_distinct_id2
WHERE team_id = %(team_id)s{value_filter}
GROUP BY distinct_id
HAVING argMax(is_deleted, version) = 0
ORDER BY value ASC
LIMIT 20
"""


def _get_distinct_id_values(team: Team, value: Optional[str]) -> list:
    params: dict = {"team_id": team.pk}
    value_filter = ""
    if value:
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        value_filter = " AND distinct_id ILIKE %(value)s"
        params["value"] = f"%{escaped}%"
    return insight_sync_execute(
        _SELECT_DISTINCT_IDS_SQL.format(value_filter=value_filter),
        params,
        query_type="get_person_distinct_id_values",
        team_id=team.pk,
    )
