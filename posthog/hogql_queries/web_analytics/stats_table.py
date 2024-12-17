from typing import Union

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql.property import (
    property_to_expr,
    get_property_operator,
    get_property_value,
    get_property_type,
    get_property_key,
)
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
    map_columns,
)
from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    WebStatsTableQuery,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
    EventPropertyFilter,
    PersonPropertyFilter,
)

BREAKDOWN_NULL_DISPLAY = "(none)"


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
            if self.query.conversionGoal:
                return self.to_main_query(self._counts_breakdown_value())
            elif self.query.includeScrollDepth and self.query.includeBounceRate:
                return self.to_path_scroll_bounce_query()
            elif self.query.includeBounceRate:
                return self.to_path_bounce_query()

        if self.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
            if self.query.includeBounceRate:
                return self.to_entry_bounce_query()

        return self.to_main_query(self._counts_breakdown_value())

    def to_main_query(self, breakdown) -> ast.SelectQuery:
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
                        ast.Alias(
                            alias="context.columns.conversion_rate",
                            expr=ast.Tuple(
                                exprs=[
                                    parse_expr(
                                        "if(`context.columns.visitors`.1 = 0, NULL, `context.columns.unique_conversions`.1 / `context.columns.visitors`.1)"
                                    ),
                                    parse_expr(
                                        "if(`context.columns.visitors`.2 = 0, NULL, `context.columns.unique_conversions`.2 / `context.columns.visitors`.2)"
                                    ),
                                ]
                            ),
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
                select_from=ast.JoinExpr(table=self._main_inner_query(breakdown)),
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
        query = self.to_main_query(self._bounce_entry_pathname_breakdown())

        if self.query.conversionGoal is None:
            query.select.append(self._period_comparison_tuple("is_bounce", "context.columns.bounce_rate", "avg"))

        return query

    def to_path_scroll_bounce_query(self) -> ast.SelectQuery:
        with self.timings.measure("stats_table_bounce_query"):
            query = parse_select(
                """
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
        uniqIf(filtered_person_id, {current_period}) AS visitors,
        uniqIf(filtered_person_id, {previous_period}) AS previous_visitors,
        sumIf(filtered_pageview_count, {current_period}) AS views,
        sumIf(filtered_pageview_count, {previous_period}) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp ) AS start_timestamp
        FROM events
        WHERE and(
            events.event == '$pageview',
            breakdown_value IS NOT NULL,
            {inside_periods},
            {event_properties},
            {session_properties},
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, {current_period}) AS bounce_rate,
        avgIf(is_bounce, {previous_period}) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) as start_timestamp
        FROM events
        WHERE and(
            events.event == '$pageview',
            breakdown_value IS NOT NULL,
            {inside_periods},
            {event_properties},
            {session_properties},
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
LEFT JOIN (
    SELECT
        breakdown_value,
        avgMergeIf(average_scroll_percentage_state, {current_period}) AS average_scroll_percentage,
        avgMergeIf(average_scroll_percentage_state, {previous_period}) AS previous_average_scroll_percentage,
        avgMergeIf(scroll_gt80_percentage_state, {current_period}) AS scroll_gt80_percentage,
        avgMergeIf(scroll_gt80_percentage_state, {previous_period}) AS previous_scroll_gt80_percentage
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
            or(events.event == '$pageview', events.event == '$pageleave'),
            breakdown_value IS NOT NULL,
            {inside_periods},
            {event_properties_for_scroll},
            {session_properties},
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
                    "breakdown_value": self._counts_breakdown_value(),
                    "scroll_breakdown_value": self._scroll_prev_pathname_breakdown(),
                    "bounce_breakdown_value": self._bounce_entry_pathname_breakdown(),
                    "current_period": self._current_period_expression(),
                    "previous_period": self._previous_period_expression(),
                    "inside_periods": self._periods_expression(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def to_path_bounce_query(self) -> ast.SelectQuery:
        if self.query.breakdownBy not in [WebStatsBreakdown.INITIAL_PAGE, WebStatsBreakdown.PAGE]:
            raise NotImplementedError("Bounce rate is only supported for page breakdowns")

        with self.timings.measure("stats_table_scroll_query"):
            query = parse_select(
                """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",
    tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS "context.columns.bounce_rate"
FROM (
    SELECT
        breakdown_value,
        uniqIf(filtered_person_id, {current_period}) AS visitors,
        uniqIf(filtered_person_id, {previous_period}) AS previous_visitors,
        sumIf(filtered_pageview_count, {current_period}) AS views,
        sumIf(filtered_pageview_count, {previous_period}) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            events.event == '$pageview',
            {inside_periods},
            {event_properties},
            {session_properties},
            {where_breakdown},
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) as counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, {current_period}) AS bounce_rate,
        avgIf(is_bounce, {previous_period}) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            events.event == '$pageview',
            breakdown_value IS NOT NULL,
            {inside_periods},
            {event_properties},
            {session_properties},
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
                    "bounce_breakdown_value": self._bounce_entry_pathname_breakdown(),
                    "current_period": self._current_period_expression(),
                    "previous_period": self._previous_period_expression(),
                    "inside_periods": self._periods_expression(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _main_inner_query(self, breakdown):
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
WHERE and({inside_periods}, {event_where}, {all_properties}, {where_breakdown})
GROUP BY session_id, breakdown_value
""",
            timings=self.timings,
            placeholders={
                "breakdown_value": breakdown,
                "event_where": self.event_type_expr,
                "all_properties": self._all_properties(),
                "where_breakdown": self.where_breakdown(),
                "inside_periods": self._periods_expression(),
            },
        )

        assert isinstance(query, ast.SelectQuery)

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
        if not self.query_compare_to_date_range:
            return ast.Call(name=function_name, args=[ast.Field(chain=[column_name])])

        return self.period_aggregate(
            function_name,
            column_name,
            self.query_date_range.date_from_as_hogql(),
            self.query_date_range.date_to_as_hogql(),
        )

    def _previous_period_aggregate(self, function_name, column_name):
        if not self.query_compare_to_date_range:
            return ast.Constant(value=None)

        return self.period_aggregate(
            function_name,
            column_name,
            self.query_compare_to_date_range.date_from_as_hogql(),
            self.query_compare_to_date_range.date_to_as_hogql(),
        )

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

    def _session_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

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
