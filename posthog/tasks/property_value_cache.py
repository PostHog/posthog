import json
import time
import uuid
from typing import Optional

from django.utils import timezone

from celery import shared_task
from opentelemetry import trace
from statshog.defaults.django import statsd

from posthog.hogql import ast
from posthog.hogql.property_utils import create_property_conditions
from posthog.hogql.query import execute_hogql_query

from posthog.api.property_value_cache import cache_property_values, clear_task_running
from posthog.queries.property_values import get_person_property_values_for_key
from posthog.tasks.utils import CeleryQueue
from posthog.utils import convert_property_value, flatten, relative_date_parse

tracer = trace.get_tracer(__name__)


def run_event_property_query_and_cache(
    team_id: int,
    property_key: str,
    is_column: bool,
    search_value: Optional[str],
    event_names: Optional[list[str]],
    property_filters: list[list[str]],
) -> list[dict]:
    """Run event property values query, cache results, and return formatted values."""
    from posthog.models.team.team import Team

    team = Team.objects.get(pk=team_id)

    with tracer.start_as_current_span("events_api_event_property_values") as span:
        span.set_attribute("team_id", team_id)
        span.set_attribute("property_key", property_key)
        span.set_attribute("is_column", is_column)
        span.set_attribute("has_value_filter", search_value is not None)
        span.set_attribute("event_names_count", len(event_names) if event_names else 0)

        date_from = relative_date_parse("-7d", team.timezone_info).strftime("%Y-%m-%d 00:00:00")
        date_to = timezone.now().strftime("%Y-%m-%d 23:59:59")

        chain: list[str | int] = [property_key] if is_column else ["properties", property_key]
        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_from),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_to),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=chain),
                right=ast.Constant(value=None),
            ),
        ]

        for param_key, param_value in property_filters:
            filter_key = param_key.replace("properties_", "", 1)
            try:
                filter_values = (
                    json.loads(param_value) if isinstance(param_value, str | bytes | bytearray) else param_value
                )
                conditions.append(create_property_conditions(filter_key, filter_values))
            except json.JSONDecodeError:
                conditions.append(create_property_conditions(filter_key, param_value))
        span.set_attribute("property_filter_count", len(property_filters))

        if event_names:
            event_conditions: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=event_name),
                )
                for event_name in event_names
            ]
            conditions.append(ast.Or(exprs=event_conditions) if len(event_conditions) > 1 else event_conditions[0])

        if search_value:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike,
                    left=ast.Call(name="toString", args=[ast.Field(chain=chain)]),
                    right=ast.Constant(value=f"%{search_value}%"),
                )
            )

        order_by = (
            [
                ast.OrderExpr(
                    expr=ast.Call(name="length", args=[ast.Call(name="toString", args=[ast.Field(chain=chain)])]),
                    order="ASC",
                )
            ]
            if search_value
            else []
        )

        query = ast.SelectQuery(
            select=[ast.Field(chain=chain)],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=conditions),
            order_by=order_by,
            limit=ast.Constant(value=10),
        )

        # TEST DELAY: Emulate slow query for testing purposes
        time.sleep(5)

        result = execute_hogql_query(query, team=team)

        values = []
        for row in result.results:
            if isinstance(row[0], float | int | bool | uuid.UUID):
                values.append(row[0])
            else:
                try:
                    values.append(json.loads(row[0]))
                except json.JSONDecodeError:
                    values.append(row[0])

        span.set_attribute("result_count", len(values))
        formatted_values = [{"name": convert_property_value(v)} for v in flatten(values)]

        if not property_filters:
            cache_property_values(
                team_id=team_id,
                property_type="event",
                property_key=property_key,
                values=formatted_values,
                search_value=search_value,
                event_names=event_names,
            )

        clear_task_running(
            team_id=team_id,
            property_type="event",
            property_key=property_key,
            search_value=search_value,
            event_names=event_names,
        )

        return formatted_values


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def refresh_event_property_values_cache(
    team_id: int,
    property_key: str,
    is_column: bool,
    search_value: Optional[str],
    event_names: Optional[list[str]],
    property_filters: list[list[str]],
) -> None:
    run_event_property_query_and_cache(team_id, property_key, is_column, search_value, event_names, property_filters)


def run_person_property_query_and_cache(
    team_id: int,
    property_key: str,
    search_value: Optional[str],
) -> list[dict]:
    """Run person property values query, cache results, and return formatted values."""
    from posthog.models.team.team import Team

    team = Team.objects.get(pk=team_id)

    # TEST DELAY: Emulate slow query for testing purposes
    time.sleep(5)

    result = get_person_property_values_for_key(property_key, team, search_value)
    statsd.incr("get_person_property_values_for_key_success", tags={"team_id": team_id})

    formatted_values = []
    if isinstance(result, list):
        for val, count in result:
            try:
                formatted_values.append({"name": convert_property_value(json.loads(val)), "count": count})
            except json.decoder.JSONDecodeError:
                formatted_values.append({"name": convert_property_value(val), "count": count})

        cache_property_values(
            team_id=team_id,
            property_type="person",
            property_key=property_key,
            values=formatted_values,
            search_value=search_value,
        )

    clear_task_running(
        team_id=team_id,
        property_type="person",
        property_key=property_key,
        search_value=search_value,
    )

    return formatted_values


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def refresh_person_property_values_cache(
    team_id: int,
    property_key: str,
    search_value: Optional[str],
) -> None:
    run_person_property_query_and_cache(team_id, property_key, search_value)
