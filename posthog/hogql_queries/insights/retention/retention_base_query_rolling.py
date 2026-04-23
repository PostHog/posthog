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

        t0_expr: ast.Expr
        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            t0_expr = self.get_first_time_anchor_expr()
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
