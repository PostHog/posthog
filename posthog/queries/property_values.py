from typing import Optional

from django.utils import timezone

from opentelemetry import trace

from posthog.models.event.sql import SELECT_PROP_VALUES_SQL_WITH_FILTER
from posthog.models.person.sql import SELECT_PERSON_PROP_VALUES_SQL, SELECT_PERSON_PROP_VALUES_SQL_WITH_FILTER
from posthog.models.property.util import get_property_string_expr
from posthog.models.team import Team
from posthog.queries.insight import insight_sync_execute
from posthog.utils import relative_date_parse

tracer = trace.get_tracer(__name__)


def get_property_values_for_key(
    key: str,
    team: Team,
    event_names: Optional[list[str]] = None,
    value: Optional[str] = None,
):
    with tracer.start_as_current_span("get_property_values_for_key") as span:
        span.set_attribute("team_id", team.pk)
        span.set_attribute("property_key", key)
        span.set_attribute("has_value_filter", value is not None)
        span.set_attribute("event_names_count", len(event_names) if event_names else 0)

        property_field, mat_column_exists = get_property_string_expr("events", key, "%(key)s", "properties")
        span.set_attribute("materialized_column", mat_column_exists)

        parsed_date_from = "AND timestamp >= '{}'".format(
            relative_date_parse("-7d", team.timezone_info).strftime("%Y-%m-%d 00:00:00")
        )
        parsed_date_to = "AND timestamp <= '{}'".format(timezone.now().strftime("%Y-%m-%d 23:59:59"))
        property_exists_filter = ""
        event_filter = ""
        value_filter = ""
        order_by_clause = ""
        extra_params = {}

        if mat_column_exists:
            property_exists_filter = "AND notEmpty({})".format(property_field)
        else:
            property_exists_filter = "AND JSONHas(properties, %(key)s)"
            extra_params["key"] = key

        if event_names is not None and len(event_names) > 0:
            event_conditions_list = []
            for index, event_name in enumerate(event_names):
                event_conditions_list.append(f"event = %(event_{index})s")
                extra_params[f"event_{index}"] = event_name

            event_conditions = " OR ".join(event_conditions_list)
            event_filter = "AND ({})".format(event_conditions)

        if value:
            value_filter = "AND {} ILIKE %(value)s".format(property_field)
            extra_params["value"] = "%{}%".format(value)

            order_by_clause = f"order by length({property_field})"

        result = insight_sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER.format(
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                property_field=property_field,
                event_filter=event_filter,
                value_filter=value_filter,
                property_exists_filter=property_exists_filter,
                order_by_clause=order_by_clause,
            ),
            {"team_id": team.pk, "key": key, **extra_params},
            query_type="get_property_values_with_value",
            team_id=team.pk,
        )
        span.set_attribute("result_count", len(result))
        return result


def get_person_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    with tracer.start_as_current_span("get_person_property_values_for_key") as span:
        span.set_attribute("team_id", team.pk)
        span.set_attribute("property_key", key)
        span.set_attribute("has_value_filter", value is not None)

        property_field, _ = get_property_string_expr("person", key, "%(key)s", "properties")

        if value:
            result = insight_sync_execute(
                SELECT_PERSON_PROP_VALUES_SQL_WITH_FILTER.format(property_field=property_field),
                {"team_id": team.pk, "key": key, "value": "%{}%".format(value)},
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
