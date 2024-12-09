from typing import Optional, Union

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql.property import (
    property_to_expr,
    get_property_operator,
    get_property_value,
    get_property_type,
    get_property_key,
    action_to_expr,
)
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
    map_columns,
)
from posthog.models import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    ActionConversionGoal,
    CustomEventConversionGoal,
    CachedWebStatsTableQueryResponse,
    WebStatsTableQuery,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
    EventPropertyFilter,
    PersonPropertyFilter,
)

BREAKDOWN_NULL_DISPLAY = "(none)"


# TODO: Extend `conversion_goal` support to queries besides `to_main_query`
# TODO: Add test cases for conversion goal, both action, and event-based ones
class WebStatsTableQueryRunner(WebAnalyticsQueryRunner):
    query: WebStatsTableQuery
    response: WebStatsTableQueryResponse
    cached_response: CachedWebStatsTableQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def to_query(self) -> ast.SelectQuery:
        if self.query.breakdownBy == WebStatsBreakdown.PAGE:
            if self.query.includeScrollDepth and self.query.includeBounceRate:
                return self.to_path_scroll_bounce_query()
            elif self.query.includeBounceRate:
                return self.to_path_bounce_query()

        if self.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            if self.query.includeBounceRate:
                return self.to_entry_bounce_query()

        return self.to_main_query(
            self._counts_breakdown_value(), include_session_properties=self._has_session_properties()
        )

    def to_main_query(self, breakdown, *, include_session_properties=False) -> ast.SelectQuery:
        with self.timings.measure("stats_table_query"):
            # Base selects, always returns the breakdown value, and the total number of visitors
            selects = [
                ast.Alias(alias="context.columns.breakdown_value", expr=self._processed_breakdown_value()),
                self._period_comparison_tuple("filtered_person_id", "context.columns.visitors", "uniq"),
            ]

            if self.query.conversionGoal is not None:
                selects.extend(
                    [
                        self._period_comparison_tuple("conversion_count", "context.columns.total_conversions", "sum"),
                        self._period_comparison_tuple(
                            "conversion_person_id", "context.columns.unique_conversions", "uniq"
                        ),
                    ]
                )
            else:
                selects.append(
                    self._period_comparison_tuple("filtered_pageview_count", "context.columns.views", "sum"),
                )

                if self._include_extra_aggregation_value():
                    selects.append(self._extra_aggregation_value())

            query = ast.SelectQuery(
                select=selects,
                select_from=ast.JoinExpr(
                    table=self._main_inner_query(
                        breakdown,
                        include_session_properties=include_session_properties,
                    )
                ),
                group_by=[ast.Field(chain=["context.columns.breakdown_value"])],
                order_by=[
                    ast.OrderExpr(expr=ast.Field(chain=["context.columns.visitors"]), order="DESC"),
                    ast.OrderExpr(
                        expr=ast.Field(
                            chain=[
                                "context.columns.views"
                                if self.query.conversionGoal is None
                                else "context.columns.total_conversions"
                            ]
                        ),
                        order="DESC",
                    ),
                    ast.OrderExpr(expr=ast.Field(chain=["context.columns.breakdown_value"]), order="ASC"),
                ],
            )

        return query

    def to_entry_bounce_query(self) -> ast.SelectQuery:
        query = self.to_main_query(self._bounce_entry_pathname_breakdown(), include_session_properties=True)

        if self.query.conversionGoal is None:
            query.select.append(self._period_comparison_tuple("is_bounce", "context.columns.bounce_rate", "avg"))

        return query

    # TODO: Support conversion goal
    def to_path_scroll_bounce_query(self) -> ast.SelectQuery:
        with self.timings.measure("stats_table_bounce_query"):
            query = parse_select(
                """
WITH
    start_timestamp >= {date_from} AND start_timestamp < {date_to} AS current_period_segment,
    start_timestamp >= {date_from_previous_period} AND start_timestamp < {date_from} AS previous_period_segment
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",
    tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS "context.columns.bounce_rate",
    tuple(scroll.average_scroll_percentage, scroll.previous_average_scroll_percentage) AS "context.columns.average_scroll_percentage",
    tuple(scroll.scroll_gt80_percentage, scroll.previous_scroll_gt80_percentage) AS "context.columns.scroll_gt80_percentage",
FROM (
    SELECT
        breakdown_value,
        uniqIf(filtered_person_id, current_period_segment) AS visitors,
        uniqIf(filtered_person_id, previous_period_segment) AS previous_visitors,
        sumIf(filtered_pageview_count, current_period_segment) AS views,
        sumIf(filtered_pageview_count, previous_period_segment) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp ) AS start_timestamp
        FROM events
        WHERE and(
            timestamp >= {date_from_previous_period},
            timestamp < {date_to},
            events.event == '$pageview',
            {event_properties},
            {session_properties},
            breakdown_value IS NOT NULL
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, current_period_segment) AS bounce_rate,
        avgIf(is_bounce, previous_period_segment) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) as start_timestamp
        FROM events
        WHERE and(
            timestamp >= {date_from_previous_period},
            timestamp < {date_to},
            events.event == '$pageview',
            {event_properties},
            {session_properties},
            breakdown_value IS NOT NULL
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
LEFT JOIN (
    SELECT
        breakdown_value,
        avgMergeIf(average_scroll_percentage_state, current_period_segment) AS average_scroll_percentage,
        avgMergeIf(average_scroll_percentage_state, previous_period_segment) AS previous_average_scroll_percentage,
        avgMergeIf(scroll_gt80_percentage_state, current_period_segment) AS scroll_gt80_percentage,
        avgMergeIf(scroll_gt80_percentage_state, previous_period_segment) AS previous_scroll_gt80_percentage
    FROM (
        SELECT
            {scroll_breakdown_value} AS breakdown_value, -- use $prev_pageview_pathname to find the scroll depth when leaving this pathname
            avgState(CASE
                WHEN toFloat(events.properties.`$prev_pageview_max_content_percentage`) IS NULL THEN NULL
                WHEN toFloat(events.properties.`$prev_pageview_max_content_percentage`) > 0.8 THEN 1
                ELSE 0
                END
            ) AS scroll_gt80_percentage_state,
            avgState(toFloat(events.properties.`$prev_pageview_max_scroll_percentage`)) as average_scroll_percentage_state,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            timestamp >= {date_from_previous_period},
            timestamp < {date_to},
            or(events.event == '$pageview', events.event == '$pageleave'),
            {event_properties_for_scroll},
            {session_properties},
            breakdown_value IS NOT NULL
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS scroll
ON counts.breakdown_value = scroll.breakdown_value
ORDER BY "context.columns.visitors" DESC,
"context.columns.views" DESC,
"context.columns.breakdown_value" ASC
""",
                timings=self.timings,
                placeholders={
                    "session_properties": self._session_properties(),
                    "event_properties": self._event_properties(),
                    "event_properties_for_scroll": self._event_properties_for_scroll(),
                    "date_from_previous_period": self._date_from_previous_period(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                    "breakdown_value": self._counts_breakdown_value(),
                    "scroll_breakdown_value": self._scroll_prev_pathname_breakdown(),
                    "bounce_breakdown_value": self._bounce_entry_pathname_breakdown(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    # TODO: Support conversion goal
    def to_path_bounce_query(self) -> ast.SelectQuery:
        if self.query.breakdownBy not in [WebStatsBreakdown.INITIAL_PAGE, WebStatsBreakdown.PAGE]:
            raise NotImplementedError("Bounce rate is only supported for page breakdowns")

        with self.timings.measure("stats_table_scroll_query"):
            query = parse_select(
                """
WITH
    start_timestamp >= {date_from} AND start_timestamp < {date_to} AS current_period_segment,
    start_timestamp >= {date_from_previous_period} AND start_timestamp < {date_from} AS previous_period_segment
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",
    tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS "context.columns.bounce_rate"
FROM (
    SELECT
        breakdown_value,
        uniqIf(filtered_person_id, current_period_segment) AS visitors,
        uniqIf(filtered_person_id, previous_period_segment) AS previous_visitors,
        sumIf(filtered_pageview_count, current_period_segment) AS views,
        sumIf(filtered_pageview_count, previous_period_segment) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            timestamp >= {date_from_previous_period},
            timestamp < {date_to},
            events.event == '$pageview',
            {event_properties},
            {session_properties},
            {where_breakdown}
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) as counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, current_period_segment) AS bounce_rate,
        avgIf(is_bounce, previous_period_segment) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            timestamp >= {date_from_previous_period},
            timestamp < {date_to},
            events.event == '$pageview',
            {event_properties},
            {session_properties},
            breakdown_value IS NOT NULL
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) as bounce
ON counts.breakdown_value = bounce.breakdown_value
ORDER BY "context.columns.visitors" DESC,
"context.columns.views" DESC,
"context.columns.breakdown_value" ASC
""",
                timings=self.timings,
                placeholders={
                    "breakdown_value": self._counts_breakdown_value(),
                    "where_breakdown": self.where_breakdown(),
                    "session_properties": self._session_properties(),
                    "event_properties": self._event_properties(),
                    "date_from_previous_period": self._date_from_previous_period(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                    "bounce_breakdown_value": self._bounce_entry_pathname_breakdown(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _main_inner_query(self, breakdown, *, include_session_properties=False):
        query = parse_select(
            """
SELECT
    any(person_id) AS filtered_person_id,
    count() AS filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    session.session_id AS session_id,
    any(session.$is_bounce) AS is_bounce,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and(timestamp >= {date_from}, timestamp < {date_to}, events.event == '$pageview', {all_properties}, {where_breakdown})
GROUP BY session_id, breakdown_value
""",
            timings=self.timings,
            placeholders={
                "breakdown_value": breakdown,
                "date_from": self._date_from_previous_period(),
                "date_to": self._date_to(),
                "all_properties": self._all_properties(),
                "where_breakdown": self.where_breakdown(),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        if include_session_properties:
            query.where.args.append(self._session_properties())  # query.where is an `ast.Call`

        if self.conversion_count_expr and self.conversion_person_id_expr:
            query.select.append(ast.Alias(alias="conversion_count", expr=self.conversion_count_expr))
            query.select.append(ast.Alias(alias="conversion_person_id", expr=self.conversion_person_id_expr))

        return query

    def _period_comparison_tuple(self, column, alias, function_name):
        return ast.Alias(
            alias=alias,
            expr=ast.Tuple(
                exprs=[
                    self._current_period_aggregate(function_name, column),
                    self._previous_period_aggregate(function_name, column),
                ]
            ),
        )

    def _current_period_aggregate(self, function_name, column_name):
        return self.period_aggregate(function_name, column_name, self._date_from(), self._date_to())

    def _previous_period_aggregate(self, function_name, column_name):
        return self.period_aggregate(function_name, column_name, self._date_from_previous_period(), self._date_from())

    # Reproduction from `web_analytics/web_overview.py`
    # Update in both places
    @cached_property
    def conversion_goal_expr(self) -> Optional[ast.Expr]:
        if isinstance(self.query.conversionGoal, ActionConversionGoal):
            action = Action.objects.get(pk=self.query.conversionGoal.actionId, team__project_id=self.team.project_id)
            return action_to_expr(action)
        elif isinstance(self.query.conversionGoal, CustomEventConversionGoal):
            return ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.query.conversionGoal.customEventName),
            )
        else:
            return None

    # Reproduction from `web_analytics/web_overview.py`
    # Update in both places
    @cached_property
    def conversion_count_expr(self) -> Optional[ast.Expr]:
        if self.conversion_goal_expr:
            return ast.Call(name="countIf", args=[self.conversion_goal_expr])
        else:
            return None

    # Reproduction from `web_analytics/web_overview.py`
    # Update in both places
    @cached_property
    def conversion_person_id_expr(self) -> Optional[ast.Expr]:
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
            return None

    def _event_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _event_properties_for_scroll(self) -> ast.Expr:
        def map_scroll_property(property: Union[EventPropertyFilter, PersonPropertyFilter]):
            if get_property_type(property) == "event" and get_property_key(property) == "$pathname":
                return EventPropertyFilter(
                    key="$prev_pageview_pathname",
                    operator=get_property_operator(property),
                    value=get_property_value(property),
                )
            return property

        properties = [
            map_scroll_property(p)
            for p in self.query.properties + self._test_account_filters
            if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _has_session_properties(self) -> bool:
        return any(
            get_property_type(p) == "session" for p in self.query.properties + self._test_account_filters
        ) or self.query.breakdownBy in {
            WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
            WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
            WebStatsBreakdown.INITIAL_UTM_SOURCE,
            WebStatsBreakdown.INITIAL_UTM_CAMPAIGN,
            WebStatsBreakdown.INITIAL_UTM_MEDIUM,
            WebStatsBreakdown.INITIAL_UTM_TERM,
            WebStatsBreakdown.INITIAL_UTM_CONTENT,
            WebStatsBreakdown.INITIAL_PAGE,
            WebStatsBreakdown.EXIT_PAGE,
            WebStatsBreakdown.INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN,
        }

    def _session_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def _date_to(self) -> ast.Expr:
        return self.query_date_range.date_to_as_hogql()

    def _date_from(self) -> ast.Expr:
        return self.query_date_range.date_from_as_hogql()

    def _date_from_previous_period(self) -> ast.Expr:
        return self.query_date_range.previous_period_date_from_as_hogql()

    # TODO: Calculate conversion rate
    def calculate(self):
        query = self.to_query()
        response = self.paginator.execute_hogql_query(
            query_type="stats_table_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = self.paginator.results

        assert results is not None

        results_mapped = map_columns(
            results,
            {
                0: self._join_with_aggregation_value,  # breakdown_value
                1: lambda tuple, row: (  # Views (tuple)
                    self._unsample(tuple[0], row),
                    self._unsample(tuple[1], row),
                ),
                2: lambda tuple, row: (  # Visitors (tuple)
                    self._unsample(tuple[0], row),
                    self._unsample(tuple[1], row),
                ),
            },
        )

        columns = response.columns

        if self.query.breakdownBy == WebStatsBreakdown.LANGUAGE:
            # Keep only first 3 columns, we don't need the aggregation value in the frontend
            # Remove both the value and the column (used to generate table headers)
            results_mapped = [row[:3] for row in results_mapped]

            columns = (
                [column for column in response.columns if column != "context.columns.aggregation_value"]
                if response.columns is not None
                else response.columns
            )

        # Add last conversion rate column
        if self.query.conversionGoal is not None:
            for result in results_mapped:
                unique_visitors = result[1]
                unique_conversions = result[-1]

                # Keep them in the same tuple format we already have
                result.append(
                    (
                        unique_conversions[0] / unique_visitors[0] if unique_visitors[0] != 0 else None,
                        unique_conversions[1] / unique_visitors[1] if unique_visitors[1] != 0 else None,
                    )
                )

            # Guarantee new column exists
            columns.append("context.columns.conversion_rate")

        return WebStatsTableQueryResponse(
            columns=columns,
            results=results_mapped,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def _join_with_aggregation_value(self, breakdown_value: str, row: list):
        if self.query.breakdownBy != WebStatsBreakdown.LANGUAGE:
            return breakdown_value

        return f"{breakdown_value}-{row[3]}"  # Fourth value is the aggregation value

    def _counts_breakdown_value(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.PAGE:
                return self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$pathname"]))
            case WebStatsBreakdown.INITIAL_PAGE:
                return self._apply_path_cleaning(ast.Field(chain=["session", "$entry_pathname"]))
            case WebStatsBreakdown.EXIT_PAGE:
                return self._apply_path_cleaning(ast.Field(chain=["session", "$end_pathname"]))
            case WebStatsBreakdown.EXIT_CLICK:
                return ast.Field(chain=["session", "$last_external_click_url"])
            case WebStatsBreakdown.INITIAL_REFERRING_DOMAIN:
                return ast.Field(chain=["session", "$entry_referring_domain"])
            case WebStatsBreakdown.INITIAL_UTM_SOURCE:
                return ast.Field(chain=["session", "$entry_utm_source"])
            case WebStatsBreakdown.INITIAL_UTM_CAMPAIGN:
                return ast.Field(chain=["session", "$entry_utm_campaign"])
            case WebStatsBreakdown.INITIAL_UTM_MEDIUM:
                return ast.Field(chain=["session", "$entry_utm_medium"])
            case WebStatsBreakdown.INITIAL_UTM_TERM:
                return ast.Field(chain=["session", "$entry_utm_term"])
            case WebStatsBreakdown.INITIAL_UTM_CONTENT:
                return ast.Field(chain=["session", "$entry_utm_content"])
            case WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
                return ast.Field(chain=["session", "$channel_type"])
            case WebStatsBreakdown.INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN:
                return ast.Call(
                    name="concatWithSeparator",
                    args=[
                        ast.Constant(value=" / "),
                        coalesce_with_null_display(
                            ast.Field(chain=["session", "$entry_utm_source"]),
                            ast.Field(chain=["session", "$entry_referring_domain"]),
                        ),
                        coalesce_with_null_display(ast.Field(chain=["session", "$entry_utm_medium"])),
                        coalesce_with_null_display(ast.Field(chain=["session", "$entry_utm_campaign"])),
                    ],
                )
            case WebStatsBreakdown.BROWSER:
                return ast.Field(chain=["properties", "$browser"])
            case WebStatsBreakdown.OS:
                return ast.Field(chain=["properties", "$os"])
            case WebStatsBreakdown.DEVICE_TYPE:
                return ast.Field(chain=["properties", "$device_type"])
            case WebStatsBreakdown.COUNTRY:
                return ast.Field(chain=["properties", "$geoip_country_code"])
            case WebStatsBreakdown.REGION:
                return parse_expr(
                    "tuple(properties.$geoip_country_code, properties.$geoip_subdivision_1_code, properties.$geoip_subdivision_1_name)"
                )
            case WebStatsBreakdown.CITY:
                return parse_expr("tuple(properties.$geoip_country_code, properties.$geoip_city_name)")
            case WebStatsBreakdown.LANGUAGE:
                return ast.Field(chain=["properties", "$browser_language"])
            case WebStatsBreakdown.TIMEZONE:
                # Get the difference between the UNIX timestamp at UTC and the UNIX timestamp at the event's timezone
                # Value is in milliseconds, turn it to hours, works even for fractional timezone offsets (I'm looking at you, Australia)
                return parse_expr(
                    "if(or(isNull(properties.$timezone), empty(properties.$timezone), properties.$timezone == 'Etc/Unknown'), NULL, (toUnixTimestamp64Milli(parseDateTimeBestEffort(assumeNotNull(toString(timestamp, properties.$timezone)))) - toUnixTimestamp64Milli(parseDateTimeBestEffort(assumeNotNull(toString(timestamp, 'UTC'))))) / 3600000)"
                )
            case _:
                raise NotImplementedError("Breakdown not implemented")

    def _processed_breakdown_value(self):
        if self.query.breakdownBy != WebStatsBreakdown.LANGUAGE:
            return ast.Field(chain=["breakdown_value"])

        return parse_expr("arrayElement(splitByChar('-', assumeNotNull(breakdown_value), 2), 1)")

    def _include_extra_aggregation_value(self):
        return self.query.breakdownBy == WebStatsBreakdown.LANGUAGE

    def _extra_aggregation_value(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.LANGUAGE:
                return parse_expr(
                    "arrayElement(topK(1)(arrayElement(splitByChar('-', assumeNotNull(breakdown_value), 2), 2)), 1) AS `context.columns.aggregation_value`"
                )
            case _:
                raise NotImplementedError("Aggregation value not exists")

    def where_breakdown(self):
        match self.query.breakdownBy:
            case WebStatsBreakdown.REGION | WebStatsBreakdown.CITY:
                return parse_expr("tupleElement(breakdown_value, 2) IS NOT NULL")
            case (
                WebStatsBreakdown.INITIAL_UTM_SOURCE
                | WebStatsBreakdown.INITIAL_UTM_CAMPAIGN
                | WebStatsBreakdown.INITIAL_UTM_MEDIUM
                | WebStatsBreakdown.INITIAL_UTM_TERM
                | WebStatsBreakdown.INITIAL_UTM_CONTENT
            ):
                return parse_expr("TRUE")  # actually show null values
            case WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
                return parse_expr(
                    "breakdown_value IS NOT NULL AND breakdown_value != ''"
                )  # we need to check for empty strings as well due to how the left join works
            case _:
                return parse_expr("breakdown_value IS NOT NULL")

    def _scroll_prev_pathname_breakdown(self):
        return self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$prev_pageview_pathname"]))

    def _bounce_entry_pathname_breakdown(self):
        return self._apply_path_cleaning(ast.Field(chain=["session", "$entry_pathname"]))

    def _apply_path_cleaning(self, path_expr: ast.Expr) -> ast.Expr:
        if not self.query.doPathCleaning or not self.team.path_cleaning_filters:
            return path_expr

        for replacement in self.team.path_cleaning_filter_models():
            path_expr = ast.Call(
                name="replaceRegexpAll",
                args=[
                    path_expr,
                    ast.Constant(value=replacement.regex),
                    ast.Constant(value=replacement.alias),
                ],
            )

        return path_expr


def coalesce_with_null_display(*exprs: ast.Expr) -> ast.Expr:
    return ast.Call(name="coalesce", args=[*exprs, ast.Constant(value=BREAKDOWN_NULL_DISPLAY)])
