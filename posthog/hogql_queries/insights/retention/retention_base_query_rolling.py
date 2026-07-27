from posthog.schema import EntityType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.retention.retention_base_query_builder import RetentionBaseQueryBuilder


class RetentionRollingIntervalBaseQueryBuilder(RetentionBaseQueryBuilder):
    def build_base_query(
        self,
        start_interval_index_filter: int | None = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        interval = self.query_date_range.interval_name
        if interval == "hour":
            unit, count = "hour", 1
        elif interval == "week":
            unit, count = "day", 7
        elif interval == "month":
            unit, count = "day", 30
        else:  # Day
            unit, count = "hour", 24

        has_data_warehouse_series = (
            self.start_event.type == EntityType.DATA_WAREHOUSE or self.return_event.type == EntityType.DATA_WAREHOUSE
        )
        if has_data_warehouse_series:
            return self._build_base_query_data_warehouse(unit, count)
        return self._build_base_query_events(unit, count)

    def _build_base_query_events(self, unit: str, count: int) -> ast.SelectQuery:
        t0_expr: ast.Expr
        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            t0_expr = self.get_first_time_anchor_expr(self.start_event)
        else:
            t0_expr = parse_expr("minIf(events.timestamp, {expr})", {"expr": self.start_entity_expr})

        # CTE to get t_0 for each actor
        first_event_cte = ast.SelectQuery(
            select=[
                ast.Alias(alias="actor_id", expr=ast.Field(chain=["events", self.aggregation_target_events_column])),
                ast.Alias(alias="t_0", expr=t0_expr),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=self.global_event_filters),
            group_by=[ast.Field(chain=["actor_id"])],
            having=ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq, left=ast.Field(chain=["t_0"]), right=ast.Constant(value=None)
            ),
        )

        inner_query = ast.SelectQuery(
            select=[
                ast.Alias(alias="actor_id", expr=ast.Field(chain=["actors_with_t0", "actor_id"])),
                ast.Alias(
                    alias="start_interval_index",
                    expr=parse_expr(
                        "floor(dateDiff({unit}, {date_from}, t_0) / {count})",
                        {
                            "unit": ast.Constant(value=unit),
                            "count": ast.Constant(value=count),
                            "date_from": self.query_date_range.date_from_as_hogql(),
                        },
                    ),
                ),
                ast.Alias(
                    alias="intervals_from_base",
                    expr=parse_expr(
                        """
                        arrayJoin(
                            arrayDistinct(
                                arrayConcat(
                                    [0],
                                    arrayFilter(
                                        x -> x >= 0,
                                        groupUniqArray(
                                            if(
                                                {return_entity_expr},
                                                floor(dateDiff({unit}, t_0, events.timestamp) / {count}),
                                                -1
                                            )
                                        )
                                    )
                                )
                            )
                        )
                        """,
                        {
                            "return_entity_expr": self.return_entity_expr,
                            "unit": ast.Constant(value=unit),
                            "count": ast.Constant(value=count),
                        },
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                next_join=ast.JoinExpr(
                    table=first_event_cte,
                    alias="actors_with_t0",
                    join_type="INNER JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["events", self.aggregation_target_events_column]),
                            right=ast.Field(chain=["actors_with_t0", "actor_id"]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            where=ast.And(exprs=[*self.global_event_filters, parse_expr("timestamp >= t_0")]),
            group_by=[ast.Field(chain=["actors_with_t0", "actor_id"]), ast.Field(chain=["actors_with_t0", "t_0"])],
        )

        return inner_query

    def _build_base_query_data_warehouse(self, unit: str, count: int) -> ast.SelectQuery:
        # Breakdowns are out of scope for this path: apply_breakdown references events.timestamp / events.properties,
        # which aren't in scope when the start entity is a data warehouse table. Global property filters,
        # test-account filters, and sampling are rejected upstream by DisallowUnsupportedDataWarehouseSettings.
        first_event_cte = self._build_data_warehouse_first_event_cte()

        return_is_dwh = self.return_event.type == EntityType.DATA_WAREHOUSE
        return_ts_field = self.entity_timestamp_field(self.return_event)
        return_table_name = self.return_event.table_name if return_is_dwh else "events"
        assert return_table_name
        return_actor_column = self.entity_actor_id_column(self.return_event)

        # A LEFT-joined return row counts toward an interval when it matches the return entity, falls inside the
        # window, and is at or after the actor's t_0. The >= t_0 comparison is also the discriminator that drops the
        # NULL-filled unmatched row — a no-property data warehouse return predicate is a constant True and so can't
        # do that on its own, but the timestamp comparison against a NULL row evaluates falsy.
        return_match = ast.And(
            exprs=[
                self.entity_expr_with_props(self.return_event),
                self.events_timestamp_filter(field=return_ts_field),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=return_ts_field,
                    right=ast.Field(chain=["actors_with_t0", "t_0"]),
                ),
            ]
        )

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="actor_id", expr=ast.Field(chain=["actors_with_t0", "actor_id"])),
                ast.Alias(
                    alias="start_interval_index",
                    expr=parse_expr(
                        "floor(dateDiff({unit}, {date_from}, actors_with_t0.t_0) / {count})",
                        {
                            "unit": ast.Constant(value=unit),
                            "count": ast.Constant(value=count),
                            "date_from": self.query_date_range.date_from_as_hogql(),
                        },
                    ),
                ),
                ast.Alias(
                    alias="intervals_from_base",
                    expr=parse_expr(
                        """
                        arrayJoin(
                            arrayDistinct(
                                arrayConcat(
                                    [0],
                                    arrayFilter(
                                        x -> x >= 0,
                                        groupUniqArray(
                                            if(
                                                {return_match},
                                                floor(dateDiff({unit}, actors_with_t0.t_0, {return_ts}) / {count}),
                                                -1
                                            )
                                        )
                                    )
                                )
                            )
                        )
                        """,
                        {
                            "return_match": return_match,
                            "return_ts": return_ts_field,
                            "unit": ast.Constant(value=unit),
                            "count": ast.Constant(value=count),
                        },
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=first_event_cte,
                alias="actors_with_t0",
                next_join=ast.JoinExpr(
                    table=ast.Field(chain=[return_table_name]),
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["actors_with_t0", "actor_id"]),
                            right=ast.Field(chain=[return_table_name, return_actor_column]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            group_by=[ast.Field(chain=["actors_with_t0", "actor_id"]), ast.Field(chain=["actors_with_t0", "t_0"])],
        )

    def _build_data_warehouse_first_event_cte(self) -> ast.SelectQuery:
        start_is_dwh = self.start_event.type == EntityType.DATA_WAREHOUSE
        start_ts_field = self.entity_timestamp_field(self.start_event)
        start_table_name = self.start_event.table_name if start_is_dwh else "events"
        assert start_table_name
        start_actor_column = self.entity_actor_id_column(self.start_event)
        actor_id_expr = ast.Field(chain=[start_table_name, start_actor_column])

        where: ast.Expr | None
        having: ast.Expr | None
        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            # The anchor must see the actor's true-earliest row, so the start table is scanned unwindowed; an
            # out-of-window anchor is then excluded by the window guard + HAVING (mirrors the fixed-interval DWH
            # variant's _first_time_start_event_timestamps_expr).
            anchor_expr = self.get_first_time_anchor_expr(self.start_event)
            t0_expr: ast.Expr = parse_expr(
                "if({within_window}, {anchor}, NULL)",
                {"within_window": self.events_timestamp_filter(field=anchor_expr), "anchor": anchor_expr},
            )
            where = None
            having = ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq, left=ast.Field(chain=["t_0"]), right=ast.Constant(value=None)
            )
        else:
            # Recurring: t_0 is the earliest qualifying start row inside the analysis window. The WHERE restricts the
            # group to qualifying rows so min() over a non-empty set is the cohorting timestamp (no HAVING needed).
            t0_expr = ast.Call(name="min", args=[start_ts_field])
            where = ast.And(
                exprs=[
                    self.entity_expr_with_props(self.start_event),
                    self.events_timestamp_filter(field=start_ts_field),
                ]
            )
            having = None

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="actor_id", expr=actor_id_expr),
                ast.Alias(alias="t_0", expr=t0_expr),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[start_table_name])),
            where=where,
            group_by=[ast.Field(chain=["actor_id"])],
            having=having,
        )
