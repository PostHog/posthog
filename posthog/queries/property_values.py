from typing import Optional

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.event.sql import SELECT_PROP_VALUES_SQL_WITH_FILTER
from posthog.models.property.util import get_property_string_expr
from posthog.models.team import Team
from posthog.queries.insight import insight_sync_execute
from posthog.utils import relative_date_parse


def get_property_values_for_key(
    key: str,
    team: Team,
    event_names: Optional[list[str]] = None,
    value: Optional[str] = None,
):
    property_field, mat_column_exists = get_property_string_expr("events", key, "%(key)s", "properties")
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

    return insight_sync_execute(
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


def get_person_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    placeholders: dict[str, ast.Expr] = {
        "team_id": ast.Constant(value=team.pk),
        "property_key": ast.Constant(value=key),
    }

    where_conditions = ["person.team_id = {team_id}"]
    if value:
        where_conditions.append("properties[{property_key}] ILIKE {search_value}")
        placeholders["search_value"] = ast.Constant(value=f"%{value}%")
    else:
        where_conditions.append("properties[{property_key}] IS NOT NULL")
        where_conditions.append("properties[{property_key}] != ''")
    where_clause = " AND ".join(where_conditions)

    hogql_query = f"""
        SELECT
            value,
            count(value)
        FROM (
            SELECT properties[{{property_key}}] as value
            FROM persons as person
            WHERE {where_clause}
            ORDER BY person.id DESC
            LIMIT 100000
        )
        GROUP BY value
        ORDER BY count(value) DESC
        LIMIT 20
    """

    response = execute_hogql_query(
        hogql_query,
        team=team,
        query_type="get_person_property_values_with_value" if value else "get_person_property_values",
        placeholders=placeholders,
    )

    return response.results or []
