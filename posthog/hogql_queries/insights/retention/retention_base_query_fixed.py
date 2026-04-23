from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.retention.retention_base_query_builder import RetentionBaseQueryBuilder
from posthog.queries.breakdown_props import ALL_USERS_COHORT_ID


class RetentionFixedIntervalBaseQueryBuilder(RetentionBaseQueryBuilder):
    def build_base_query(
        self,
        start_interval_index_filter: int | None = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        start_of_interval_sql = self.query_date_range.get_start_of_interval_hogql(
            source=ast.Field(chain=["events", "timestamp"])
        )

        event_filters = self.global_event_filters.copy()
        if (
            self.query.breakdownFilter
            and self.query.breakdownFilter.breakdowns
            and len(self.query.breakdownFilter.breakdowns) == 1
            and self.query.breakdownFilter.breakdowns[0].type == "cohort"
        ):
            cohort_id = self.query.breakdownFilter.breakdowns[0].property
            # Don't add cohort filter for "all users" (cohort_id = 0)
            if int(cohort_id) != ALL_USERS_COHORT_ID:
                event_filters.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.InCohort,
                        left=ast.Field(chain=["person_id"]),
                        right=ast.Constant(value=int(cohort_id)),
                    )
                )

        start_event_timestamps = parse_expr(
            """
            arraySort(
                groupUniqArrayIf(
                    {start_of_interval_sql},
                    {start_entity_expr} and
                    {filter_timestamp}
                )
            )
            """,
            {
                "start_of_interval_sql": start_of_interval_sql,
                "start_entity_expr": self.start_entity_expr,
                "filter_timestamp": self.events_timestamp_filter,
            },
        )

        minimum_occurrences = self.query.retentionFilter.minimumOccurrences or 1
        minimum_occurrences_aliases = self._get_minimum_occurrences_aliases(
            minimum_occurrences=minimum_occurrences,
            start_of_interval_sql=start_of_interval_sql,
            return_entity_expr=self.return_entity_expr,
        )

        if self.property_aggregation_expr:
            # For property aggregation, we need separate handling for start (interval 0) and return events (interval 1+).
            # Tuples are (interval_start, value, actual_timestamp); actual_timestamp is used when start and
            # return events differ to filter interval-0 return events that happen after the start event.
            #
            # These raw expressions are stored in return_event_values and added as named aliases (_start_event_data,
            # _return_event_data) in select_fields. All later references use ast.Field to those aliases instead of
            # inlining the groupArrayIf expressions. This prevents ClickHouse from creating a self-join on the events
            # table when these aggregations appear inside lambda functions (arrayFilter/arrayMap/arrayMin), which would
            # otherwise cause MEMORY_LIMIT_EXCEEDED on large datasets.
            start_event_data = parse_expr(
                """
                groupArrayIf(
                    ({start_of_interval_sql}, {property_aggregation_expr}, events.timestamp),
                    {start_entity_expr} and {filter_timestamp}
                )
                """,
                {
                    "start_of_interval_sql": start_of_interval_sql,
                    "property_aggregation_expr": self.property_aggregation_expr,
                    "start_entity_expr": self.start_entity_expr,
                    "filter_timestamp": self.events_timestamp_filter,
                },
            )
            return_event_data = self._get_return_event_timestamps_expr(
                minimum_occurrences=minimum_occurrences,
                start_of_interval_sql=start_of_interval_sql,
                return_entity_expr=self.return_entity_expr,
            )
            # Reference the pre-computed aliases rather than inlining the expressions again
            return_event_timestamps = parse_expr("arrayMap(x -> x.1, _return_event_data)")
            return_event_values = (start_event_data, return_event_data)
        else:
            return_event_timestamps = self._get_return_event_timestamps_expr(
                minimum_occurrences=minimum_occurrences,
                start_of_interval_sql=start_of_interval_sql,
                return_entity_expr=self.return_entity_expr,
            )
            return_event_values = None

        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            min_timestamp_inner_expr = self.get_first_time_anchor_expr()

            start_event_timestamps = parse_expr(
                """
                    if(
                        has(
                            {start_event_timestamps} as _start_event_timestamps,
                            {min_timestamp}
                        ),
                        _start_event_timestamps,
                        []
                    )
                """,
                {
                    "start_event_timestamps": start_event_timestamps,
                    # cast this to start of interval as well so we can compare with the timestamps fetched above
                    "min_timestamp": self.query_date_range.date_to_start_of_interval_hogql(min_timestamp_inner_expr),
                },
            )
            # interval must be same as first interval of in which start event happened
            is_valid_start_interval = parse_expr("start_event_timestamps[1] = interval_date")
            is_first_interval_after_start_event = parse_expr(
                "start_event_timestamps[1] = date_range[start_interval_index + 1]"
            )
        else:
            # start event must have happened in the interval
            is_valid_start_interval = parse_expr("has(start_event_timestamps, interval_date)")
            is_first_interval_after_start_event = parse_expr(
                "has(start_event_timestamps, date_range[start_interval_index + 1])"
            )

        intervals_from_base_array_aggregator = "arrayJoin"

        intervals_from_base_expr: ast.Expr
        retention_value_expr: ast.Expr | None = None

        if self.property_aggregation_expr and return_event_values:
            # return_event_values raw exprs are added as named SELECT aliases (_start_event_data, _return_event_data)
            # in select_fields below. Here we only build the combined_data expression using field references.
            start_event_data_ref = ast.Field(chain=["_start_event_data"])
            return_event_data_ref = ast.Field(chain=["_return_event_data"])

            # When start and return events are different event types, return events that occur
            # strictly after the start event within interval 0 are counted for that interval.
            # When they are the same event type, start_data already captures all occurrences in
            # interval 0; allowing return_data to also contribute would double-count.
            different_event_entities = (
                self.start_event.id != self.return_event.id or self.start_event.type != self.return_event.type
            )

            if different_event_entities:
                # Include return events in interval 0 (index 0 = same interval as cohort) only when
                # they happen strictly after the earliest start event in that interval.
                combined_data = parse_expr(
                    """
                    arrayConcat(
                        arrayFilter(
                            x -> x.1 >= 0,
                            arrayMap(
                                item -> (toInt(if(item.1 = date_range[start_interval_index + 1], 0, -1)), item.2),
                                {start_data}
                            )
                        ),
                        arrayFilter(
                            x -> x.1 >= 0,
                            arrayMap(
                                item -> (
                                    toInt(indexOf(
                                        arraySlice(date_range, start_interval_index + 1, {lookahead_plus_one}),
                                        item.1
                                    ) - 1),
                                    item.2
                                ),
                                arrayFilter(
                                    x -> (
                                        x.1 > date_range[start_interval_index + 1] OR (
                                            x.1 = date_range[start_interval_index + 1] AND
                                            x.3 > arrayMin(
                                                arrayMap(
                                                    y -> y.3,
                                                    arrayFilter(
                                                        z -> z.1 = date_range[start_interval_index + 1],
                                                        {start_data}
                                                    )
                                                )
                                            )
                                        )
                                    ),
                                    {return_data}
                                )
                            )
                        )
                    )
                    """,
                    {
                        "lookahead_plus_one": ast.Constant(value=self.query_date_range.lookahead + 1),
                        "start_data": start_event_data_ref,
                        "return_data": return_event_data_ref,
                    },
                )
            else:
                # Same event: return events only contribute to intervals > 0 (current behaviour).
                combined_data = parse_expr(
                    """
                    arrayConcat(
                        arrayFilter(
                            x -> x.1 >= 0,
                            arrayMap(
                                item -> (toInt(if(item.1 = date_range[start_interval_index + 1], 0, -1)), item.2),
                                {start_data}
                            )
                        ),
                        arrayFilter(
                            x -> x.1 > 0,
                            arrayMap(
                                item -> (
                                    toInt(indexOf(
                                        arraySlice(date_range, start_interval_index + 2, {lookahead}),
                                        item.1
                                    )),
                                    item.2
                                ),
                                {return_data}
                            )
                        )
                    )
                    """,
                    {
                        "lookahead": ast.Constant(value=self.query_date_range.lookahead),
                        "start_data": start_event_data_ref,
                        "return_data": return_event_data_ref,
                    },
                )

            intervals_from_base_expr = parse_expr("(arrayJoin({data})).1", {"data": combined_data})
            retention_value_expr = parse_expr("(arrayJoin({data})).2", {"data": combined_data})

        elif self.is_custom_bracket_retention:
            bucket_logic = self._get_custom_bracket_intervals_from_base_expr()
            intervals_from_base_expr = parse_expr(
                f"""
                {intervals_from_base_array_aggregator}(
                    arrayDistinct(
                        arrayConcat(
                            if({{is_first_interval_after_start_event}}, [0], []),
                            arrayFilter(
                                x -> x >= 0,
                                arrayMap(
                                    _timestamp -> {{bucket_logic}},
                                    return_event_timestamps
                                )
                            )
                        )
                    )
                )
                """,
                {
                    "is_first_interval_after_start_event": is_first_interval_after_start_event,
                    "bucket_logic": bucket_logic,
                },
            )
        else:
            intervals_from_base_expr = self._get_default_intervals_from_base_expr(
                is_first_interval_after_start_event, intervals_from_base_array_aggregator
            )

        select_fields: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["events", self.aggregation_target_events_column])),
            # start events between date_from and date_to (represented by start of interval)
            # when TARGET_FIRST_TIME, also adds filter for start (target) event performed for first time
            ast.Alias(alias="start_event_timestamps", expr=start_event_timestamps),
            # get all intervals between date_from and date_to (represented by start of interval)
            ast.Alias(
                alias="date_range",
                expr=parse_expr(
                    """
                        arrayMap(
                            x -> {date_from_start_of_interval} + {to_interval_function},
                            range(0, {intervals_between})
                        )
                    """,
                    {
                        "intervals_between": ast.Constant(value=self.query_date_range.intervals_between),
                        "date_from_start_of_interval": self.query_date_range.date_from_to_start_of_interval_hogql(),
                        "to_interval_function": ast.Call(
                            name=f"toInterval{self.query_date_range.interval_name.capitalize()}",
                            args=[ast.Field(chain=["x"])],
                        ),
                    },
                ),
            ),
            *minimum_occurrences_aliases,
        ]

        # When using aggregation mode, add the grouped data arrays as named aliases BEFORE columns that reference them.
        # This ensures ClickHouse uses the pre-aggregated arrays rather than re-executing the groupArrayIf inside
        # lambda functions, which would otherwise trigger a self-join on the events table and exceed memory limits.
        if self.property_aggregation_expr and return_event_values:
            start_event_data_raw, return_event_data_raw = return_event_values
            select_fields.append(ast.Alias(alias="_start_event_data", expr=start_event_data_raw))
            select_fields.append(ast.Alias(alias="_return_event_data", expr=return_event_data_raw))

        select_fields.extend(
            [
                # timestamps representing the start of a qualified interval (where count of events >= minimum_occurrences)
                ast.Alias(alias="return_event_timestamps", expr=return_event_timestamps),
                # exploded (0 based) indices of matching intervals for start event
                ast.Alias(
                    alias="start_interval_index",
                    expr=parse_expr(
                        """
                        arrayJoin(
                            arrayFilter(
                                x -> x > -1,
                                arrayMap(
                                (interval_index, interval_date) ->
                                    if(
                                        {is_valid_start_interval},
                                        interval_index - 1,
                                        -1
                                    ),
                                    arrayEnumerate(date_range),
                                    date_range
                                )
                            )
                        )
                    """,
                        {"is_valid_start_interval": is_valid_start_interval},
                    ),
                ),
                ast.Alias(
                    alias="intervals_from_base",
                    expr=intervals_from_base_expr,
                ),
            ]
        )

        if retention_value_expr:
            select_fields.append(ast.Alias(alias="retention_value", expr=retention_value_expr))

        inner_query = ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=event_filters),
            group_by=[ast.Field(chain=["actor_id"])],
            having=ast.And(
                exprs=[
                    (
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["start_interval_index"]),
                            right=ast.Constant(value=start_interval_index_filter),
                        )
                        if start_interval_index_filter is not None
                        else ast.Constant(value=1)
                    ),
                    (
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["breakdown_value"]),
                            right=ast.Constant(value=selected_breakdown_value),
                        )
                        if selected_breakdown_value is not None
                        else ast.Constant(value=1)
                    ),
                ]
            ),
        )

        return inner_query

    def _get_minimum_occurrences_aliases(
        self, minimum_occurrences: int, start_of_interval_sql: ast.Expr, return_entity_expr: ast.Expr
    ) -> list[ast.Alias]:
        """
        Only include the following expressions when minimum occurrences value is set and greater than one. The query
        with occurrences uses slightly more RAM, what can make some existing queries go over the max memory setting we
        have and having them stop working.
        """
        if minimum_occurrences == 1:
            return []

        return_event_timestamps_with_dupes = ast.Alias(
            alias="return_event_timestamps_with_dupes",
            expr=parse_expr(
                """
                groupArrayIf(
                    {start_of_interval_timestamp},
                    {returning_entity_expr} and
                    {filter_timestamp}
                )
                """,
                {
                    "start_of_interval_timestamp": start_of_interval_sql,
                    "returning_entity_expr": return_entity_expr,
                    "filter_timestamp": self.events_timestamp_filter,
                },
            ),
        )
        return_event_counts_by_interval = ast.Alias(
            alias="return_event_counts_by_interval",
            expr=parse_expr(
                """
                arrayMap(
                    interval_date -> countEqual(return_event_timestamps_with_dupes, interval_date),
                    date_range
                )
                """
            ),
        )
        return [return_event_timestamps_with_dupes, return_event_counts_by_interval]

    def _get_return_event_timestamps_expr(
        self, minimum_occurrences: int, start_of_interval_sql: ast.Expr, return_entity_expr: ast.Expr
    ) -> ast.Expr:
        if self.property_aggregation_expr:
            # Collect 3-tuples of (interval_start, value, actual_timestamp) for return events.
            # actual_timestamp is needed to filter same-interval return events that happen after the start event.
            return parse_expr(
                """
                groupArrayIf(
                    ({start_of_interval_timestamp}, {property_aggregation_expr}, events.timestamp),
                    {returning_entity_expr} and
                    {filter_timestamp}
                )
                """,
                {
                    "start_of_interval_timestamp": start_of_interval_sql,
                    "property_aggregation_expr": self.property_aggregation_expr,
                    "returning_entity_expr": return_entity_expr,
                    "filter_timestamp": self.events_timestamp_filter,
                },
            )

        if minimum_occurrences > 1:
            # return_event_counts_by_interval is only calculated when minimum_occurrences > 1.
            # See _get_minimum_occurrences_aliases method.
            return parse_expr(
                """
                arrayFilter(
                (date, counts) -> counts >= {minimum_occurrences},
                date_range,
                return_event_counts_by_interval,
                )
                """,
                {"minimum_occurrences": ast.Constant(value=minimum_occurrences)},
            )

        return parse_expr(
            """
                arraySort(
                    groupUniqArrayIf(
                        {start_of_interval_timestamp},
                        {returning_entity_expr} and
                        {filter_timestamp}
                    )
                )
            """,
            {
                "start_of_interval_timestamp": start_of_interval_sql,
                "returning_entity_expr": return_entity_expr,
                "filter_timestamp": self.events_timestamp_filter,
            },
        )

    def _get_default_intervals_from_base_expr(
        self, is_first_interval_after_start_event: ast.Expr, intervals_from_base_array_aggregator: str
    ) -> ast.Expr:
        return parse_expr(
            f"""
            {intervals_from_base_array_aggregator}(
                arrayConcat(
                    if(
                        {{is_first_interval_after_start_event}},
                        [0],
                        []
                    ),
                    arrayFilter(  -- index (time lag starting from start event) of interval with matching return timestamp
                        x -> x > 0, -- has to be at least one interval after start event (hence 0 and not -1 here)
                        arrayMap(
                            _timestamp ->
                                indexOf(
                                    arraySlice(  -- only look for matches for return events after start event and in the lookahead period
                                        date_range,
                                        start_interval_index + 1,  -- reset from 0 to 1 based index
                                        {self.query_date_range.lookahead}
                                    ),
                                _timestamp
                            ) - 1,
                            return_event_timestamps
                        )
                    )
                )
            )
            """,
            {
                "is_first_interval_after_start_event": is_first_interval_after_start_event,
            },
        )

    def _get_custom_bracket_intervals_from_base_expr(self) -> ast.Expr:
        if not self.query.retentionFilter.retentionCustomBrackets:
            raise ValueError("Custom brackets not defined")

        period_name = self.query_date_range.interval_name
        unit = period_name

        date_diff_expr = parse_expr(
            "dateDiff({unit}, start_event_timestamps[1], _timestamp)", {"unit": ast.Constant(value=unit)}
        )

        multi_if_args: list[ast.Expr] = [
            ast.CompareOperation(op=ast.CompareOperationOp.LtEq, left=date_diff_expr, right=ast.Constant(value=0)),
            ast.Constant(value=-1),
        ]
        cumulative_total = 0
        for i, bracket_size in enumerate(self.query.retentionFilter.retentionCustomBrackets):
            cumulative_total += int(bracket_size)
            condition = ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=date_diff_expr,
                right=ast.Constant(value=cumulative_total),
            )
            multi_if_args.append(condition)
            multi_if_args.append(ast.Constant(value=i + 1))  # 1-indexed bracket

        multi_if_args.append(ast.Constant(value=-1))  # Else, not in any bracket

        return ast.Call(name="multiIf", args=multi_if_args)
