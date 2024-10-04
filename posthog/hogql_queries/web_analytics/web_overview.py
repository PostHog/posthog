from typing import Optional, Union
import math

from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr, get_property_type, action_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.models import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    CachedWebOverviewQueryResponse,
    WebOverviewQueryResponse,
    WebOverviewQuery,
    ActionConversionGoal,
    CustomEventConversionGoal,
    SessionTableVersion,
)


class WebOverviewQueryRunner(WebAnalyticsQueryRunner):
    query: WebOverviewQuery
    response: WebOverviewQueryResponse
    cached_response: CachedWebOverviewQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        return self.outer_select

    def calculate(self):
        response = execute_hogql_query(
            query_type="overview_stats_pages_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert response.results

        row = response.results[0]

        if self.query.conversionGoal:
            results = [
                to_data("visitors", "unit", self._unsample(row[0]), self._unsample(row[1])),
                to_data("total conversions", "unit", self._unsample(row[2]), self._unsample(row[3])),
                to_data("unique conversions", "unit", self._unsample(row[4]), self._unsample(row[5])),
                to_data("conversion rate", "percentage", row[6], row[7]),
            ]
        else:
            results = [
                to_data("visitors", "unit", self._unsample(row[0]), self._unsample(row[1])),
                to_data("views", "unit", self._unsample(row[2]), self._unsample(row[3])),
                to_data("sessions", "unit", self._unsample(row[4]), self._unsample(row[5])),
                to_data("session duration", "duration_s", row[6], row[7]),
                to_data("bounce rate", "percentage", row[8], row[9], is_increase_bad=True),
            ]
            if self.query.includeLCPScore:
                results.append(
                    to_data("lcp score", "duration_ms", row[10], row[11], is_increase_bad=True),
                )

        return WebOverviewQueryResponse(
            results=results,
            samplingRate=self._sample_rate,
            modifiers=self.modifiers,
            dateFrom=self.query_date_range.date_from_str,
            dateTo=self.query_date_range.date_to_str,
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def event_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def session_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    @cached_property
    def conversion_goal_expr(self) -> ast.Expr:
        if isinstance(self.query.conversionGoal, ActionConversionGoal):
            action = Action.objects.get(pk=self.query.conversionGoal.actionId)
            return action_to_expr(action)
        elif isinstance(self.query.conversionGoal, CustomEventConversionGoal):
            return ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.query.conversionGoal.customEventName),
            )
        else:
            return ast.Constant(value=None)

    @cached_property
    def conversion_person_id_expr(self) -> ast.Expr:
        if self.conversion_goal_expr:
            return ast.Call(
                name="any",
                args=[
                    ast.Call(
                        name="if",
                        args=[
                            self.conversion_goal_expr,
                            ast.Field(chain=["events", "person_id"]),
                            ast.Constant(value=None),
                        ],
                    )
                ],
            )
        else:
            return ast.Constant(value=None)

    @cached_property
    def pageview_count_expression(self) -> ast.Expr:
        if self.conversion_goal_expr:
            return ast.Call(
                name="countIf",
                args=[
                    ast.CompareOperation(
                        left=ast.Field(chain=["event"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value="$pageview"),
                    )
                ],
            )
        else:
            return ast.Call(name="count", args=[])

    @cached_property
    def conversion_count_expr(self) -> ast.Expr:
        if self.conversion_goal_expr:
            return ast.Call(name="countIf", args=[self.conversion_goal_expr])
        else:
            return ast.Constant(value=None)

    @cached_property
    def event_type_expr(self) -> ast.Expr:
        pageview_expr = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value="$pageview")
        )

        if self.conversion_goal_expr:
            return ast.Call(name="or", args=[pageview_expr, self.conversion_goal_expr])
        else:
            return pageview_expr

    @cached_property
    def inner_select(self) -> ast.SelectQuery:
        start = self.query_date_range.previous_period_date_from_as_hogql()
        mid = self.query_date_range.date_from_as_hogql()
        end = self.query_date_range.date_to_as_hogql()

        parsed_select = parse_select(
            """
SELECT
    any(events.person_id) as person_id,
    session.session_id as session_id,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and(
    events.`$session_id` IS NOT NULL,
    {event_type_expr},
    timestamp >= {date_range_start},
    timestamp < {date_range_end},
    {event_properties},
    {session_properties}
)
GROUP BY session_id
HAVING and(
    start_timestamp >= {date_range_start},
    start_timestamp < {date_range_end}
)
        """,
            placeholders={
                "date_range_start": start if self.query.compare else mid,
                "date_range_end": end,
                "event_properties": self.event_properties(),
                "session_properties": self.session_properties(),
                "conversion_person_id_expr": self.conversion_person_id_expr,
                "event_type_expr": self.event_type_expr,
            },
        )
        assert isinstance(parsed_select, ast.SelectQuery)

        if self.query.conversionGoal:
            parsed_select.select.append(ast.Alias(alias="conversion_count", expr=self.conversion_count_expr))
            parsed_select.select.append(ast.Alias(alias="conversion_person_id", expr=self.conversion_person_id_expr))
        else:
            parsed_select.select.append(
                ast.Alias(
                    alias="session_duration",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$session_duration"])]),
                )
            )
            parsed_select.select.append(
                ast.Alias(alias="filtered_pageview_count", expr=ast.Call(name="count", args=[]))
            )
            parsed_select.select.append(
                ast.Alias(
                    alias="is_bounce", expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$is_bounce"])])
                )
            )
            if self.query.includeLCPScore:
                lcp = (
                    ast.Call(name="toFloat", args=[ast.Constant(value=None)])
                    if self.modifiers.sessionTableVersion == SessionTableVersion.V1
                    else ast.Call(name="any", args=[ast.Field(chain=["session", "$vitals_lcp"])])
                )
                parsed_select.select.append(ast.Alias(alias="lcp", expr=lcp))

        return parsed_select

    @cached_property
    def outer_select(self) -> ast.SelectQuery:
        start = self.query_date_range.previous_period_date_from_as_hogql()
        mid = self.query_date_range.date_from_as_hogql()
        end = self.query_date_range.date_to_as_hogql()

        def current_period_aggregate(function_name, column_name, alias, params=None):
            if self.query.compare:
                return ast.Alias(
                    alias=alias,
                    expr=ast.Call(
                        name=function_name + "If",
                        params=params,
                        args=[
                            ast.Field(chain=[column_name]),
                            ast.Call(
                                name="and",
                                args=[
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.GtEq,
                                        left=ast.Field(chain=["start_timestamp"]),
                                        right=mid,
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Lt,
                                        left=ast.Field(chain=["start_timestamp"]),
                                        right=end,
                                    ),
                                ],
                            ),
                        ],
                    ),
                )
            else:
                return ast.Alias(
                    alias=alias, expr=ast.Call(name=function_name, params=params, args=[ast.Field(chain=[column_name])])
                )

        def previous_period_aggregate(function_name, column_name, alias, params=None):
            if self.query.compare:
                return ast.Alias(
                    alias=alias,
                    expr=ast.Call(
                        name=function_name + "If",
                        params=params,
                        args=[
                            ast.Field(chain=[column_name]),
                            ast.Call(
                                name="and",
                                args=[
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.GtEq,
                                        left=ast.Field(chain=["start_timestamp"]),
                                        right=start,
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Lt,
                                        left=ast.Field(chain=["start_timestamp"]),
                                        right=mid,
                                    ),
                                ],
                            ),
                        ],
                    ),
                )
            else:
                return ast.Alias(alias=alias, expr=ast.Constant(value=None))

        if self.query.conversionGoal:
            select = [
                current_period_aggregate("uniq", "person_id", "unique_users"),
                previous_period_aggregate("uniq", "person_id", "previous_unique_users"),
                current_period_aggregate("sum", "conversion_count", "total_conversion_count"),
                previous_period_aggregate("sum", "conversion_count", "previous_total_conversion_count"),
                current_period_aggregate("uniq", "conversion_person_id", "unique_conversions"),
                previous_period_aggregate("uniq", "conversion_person_id", "previous_unique_conversions"),
                ast.Alias(
                    alias="conversion_rate",
                    expr=ast.Call(
                        name="divide", args=[ast.Field(chain=["unique_conversions"]), ast.Field(chain=["unique_users"])]
                    ),
                ),
                ast.Alias(
                    alias="previous_conversion_rate",
                    expr=ast.Call(
                        name="divide",
                        args=[
                            ast.Field(chain=["previous_unique_conversions"]),
                            ast.Field(chain=["previous_unique_users"]),
                        ],
                    ),
                ),
            ]
        else:
            select = [
                current_period_aggregate("uniq", "person_id", "unique_users"),
                previous_period_aggregate("uniq", "person_id", "previous_unique_users"),
                current_period_aggregate("sum", "filtered_pageview_count", "total_filtered_pageview_count"),
                previous_period_aggregate("sum", "filtered_pageview_count", "previous_filtered_pageview_count"),
                current_period_aggregate("uniq", "session_id", "unique_sessions"),
                previous_period_aggregate("uniq", "session_id", "previous_unique_sessions"),
                current_period_aggregate("avg", "session_duration", "avg_duration_s"),
                previous_period_aggregate("avg", "session_duration", "prev_avg_duration_s"),
                current_period_aggregate("avg", "is_bounce", "bounce_rate"),
                previous_period_aggregate("avg", "is_bounce", "prev_bounce_rate"),
            ]
            if self.query.includeLCPScore:
                select.extend(
                    [
                        current_period_aggregate("quantiles", "lcp", "lcp_p75", params=[ast.Constant(value=0.75)]),
                        previous_period_aggregate(
                            "quantiles", "lcp", "prev_lcp_p75", params=[ast.Constant(value=0.75)]
                        ),
                    ]
                )

        query = ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=self.inner_select),
        )
        assert isinstance(query, ast.SelectQuery)
        return query


def to_data(
    key: str,
    kind: str,
    value: Optional[Union[float, list[float]]],
    previous: Optional[Union[float, list[float]]],
    is_increase_bad: Optional[bool] = None,
) -> dict:
    if isinstance(value, list):
        value = value[0]
    if isinstance(previous, list):
        previous = previous[0]
    if value is not None and math.isnan(value):
        value = None
    if previous is not None and math.isnan(previous):
        previous = None
    if kind == "percentage":
        if value is not None:
            value = value * 100
        if previous is not None:
            previous = previous * 100
    if kind == "duration_ms":
        kind = "duration_s"
        if value is not None:
            value = value / 1000
        if previous is not None:
            previous = previous / 1000

    try:
        if value is not None and previous:
            change_from_previous_pct = round(100 * (value - previous) / previous)
        else:
            change_from_previous_pct = None
    except ValueError:
        change_from_previous_pct = None

    return {
        "key": key,
        "kind": kind,
        "isIncreaseBad": is_increase_bad,
        "value": value,
        "previous": previous,
        "changeFromPreviousPct": change_from_previous_pct,
    }
