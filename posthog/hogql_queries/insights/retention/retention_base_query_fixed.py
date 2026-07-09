from typing import TYPE_CHECKING, Literal

import posthoganalytics

from posthog.schema import EntityType, RetentionEntity

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.insights.retention.retention_base_query_builder import RetentionBaseQueryBuilder
from posthog.hogql_queries.insights.utils.breakdowns import ALL_USERS_COHORT_ID, has_breakdown_filter

if TYPE_CHECKING:
    from posthog.models import Team


RETENTION_FIXED_INTERVAL_BASE_QUERY_DWH_VARIANT_FLAG = "retention-fixed-interval-base-query-dwh-variant"


def retention_fixed_interval_base_query_use_dwh_variant(team: "Team") -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            RETENTION_FIXED_INTERVAL_BASE_QUERY_DWH_VARIANT_FLAG,
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {
                    "id": str(team.organization_id),
                },
                "project": {
                    "id": str(team.id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


class RetentionFixedIntervalBaseQueryBuilder(RetentionBaseQueryBuilder):
    def build_base_query(
        self,
        start_interval_index_filter: int | None = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        has_data_warehouse_series = (
            self.start_event.type == EntityType.DATA_WAREHOUSE or self.return_event.type == EntityType.DATA_WAREHOUSE
        )

        if has_data_warehouse_series or retention_fixed_interval_base_query_use_dwh_variant(self.team):
            return self.build_base_query_dwh(
                start_interval_index_filter=start_interval_index_filter,
                selected_breakdown_value=selected_breakdown_value,
            )

        return self.build_base_query_legacy(
            start_interval_index_filter=start_interval_index_filter,
            selected_breakdown_value=selected_breakdown_value,
        )

    def apply_sampling(self, base_query: ast.SelectQuery) -> None:
        select_from = base_query.select_from
        if select_from is not None and isinstance(select_from.table, ast.SelectSetQuery):
            if self.query.samplingFactor is None or not isinstance(self.query.samplingFactor, float):
                return
            for arm, entity in zip(select_from.table.select_queries(), [self.start_event, self.return_event]):
                if entity.type == EntityType.DATA_WAREHOUSE:
                    continue
                arm_from = arm.select_from if isinstance(arm, ast.SelectQuery) else None
                if arm_from is not None:
                    arm_from.sample = ast.SampleExpr(
                        sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))
                    )
            return

        super().apply_sampling(base_query)

    def apply_breakdown(self, base_query: ast.SelectQuery) -> None:
        select_from = base_query.select_from
        if select_from is not None and isinstance(select_from.table, ast.SelectSetQuery):
            # Variant path: breakdown_value is resolved inside each UNION ALL arm and
            # surfaced by build_base_query_dwh. The parent implementation appends
            # events.*-referencing exprs to this outer query, where only the
            # retention_events union is in scope, so it must not run here.
            return

        super().apply_breakdown(base_query)

    def _breakdown_extract_targets_events_table(self) -> bool:
        # event / event_metadata breakdowns hardcode events.properties.* and cannot be
        # resolved against a data-warehouse-table arm. person / group / cohort /
        # data_warehouse_person_property go via joins or a constant, and hogql is
        # user-authored (it may legitimately reference the DWH table's own columns), so
        # those are left to resolve normally.
        breakdown_filter = self.query.breakdownFilter
        if breakdown_filter is None:
            return False
        breakdown_type = (
            breakdown_filter.breakdowns[0].type if breakdown_filter.breakdowns else breakdown_filter.breakdown_type
        )
        return breakdown_type in ("event", "event_metadata", None)

    def _dwh_breakdown_value_arm_expr(
        self,
        entity: RetentionEntity,
        breakdown_extract: ast.Expr,
        timestamp_field: ast.Expr,
        query_kind: Literal["start", "return"],
    ) -> ast.Expr:
        # An events-table-rooted extract can't be resolved against a data-warehouse-table
        # arm; fall back to the empty bucket so the query still prints. The events arm (if
        # any) supplies the real value, surfaced by the outer max().
        if entity.type == EntityType.DATA_WAREHOUSE and self._breakdown_extract_targets_events_table():
            return ast.Constant(value="")

        if self.is_first_ever_occurrence:
            # First-ever buckets each actor by the breakdown value on their earliest START
            # event, resolved here via argMinIf(..., start_entity_expr_no_props). The events
            # return arm can only do that when it shares the events source with the start
            # entity. When the start entity is a DWH table, start_entity_expr_no_props
            # collapses to a truthy constant, so on the events return arm argMinIf would
            # instead read the actor's earliest RETURN event's value. Degrade to the empty
            # bucket — the start (DWH) arm already emits "", so the outer max() yields "".
            if (
                query_kind == "return"
                and self.start_event.type == EntityType.DATA_WAREHOUSE
                and self._breakdown_extract_targets_events_table()
            ):
                return ast.Constant(value="")
            # Bucket each actor by the breakdown value on their earliest start event.
            return parse_expr(
                "argMinIf({breakdown}, {timestamp}, {entity})",
                {
                    "breakdown": breakdown_extract,
                    "timestamp": timestamp_field,
                    "entity": self.start_entity_expr_no_props,
                },
            )

        # Recurring / first-time-matching: per-row value; the arm groups by it.
        return breakdown_extract

    # Nested fixed-interval query with data warehouse support.
    # Intended as a drop-in replacement for the legacy query while we verify
    # parity in production.
    def build_base_query_dwh(
        self,
        start_interval_index_filter: int | None = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        if self._can_single_scan():
            # Both arms read the same `events` source, so the two-pass UNION scans events twice for no
            # benefit. Collapse to one FROM events scan computing both timestamp arrays inline. Property
            # aggregation and any data-warehouse entity stay on the UNION below.
            return self._build_single_scan_query(start_interval_index_filter, selected_breakdown_value)

        is_valid_start_interval = self._is_valid_start_interval_expr("_start_event_timestamps")
        intervals_from_base_expr, retention_value_expr = self._get_intervals_from_base_exprs()

        start_event_query = self._build_dwh_retention_event_query(
            entity=self.start_event,
            legacy_entity_expr=self.start_entity_expr,
            query_kind="start",
        )
        return_event_query = self._build_dwh_retention_event_query(
            entity=self.return_event,
            legacy_entity_expr=self.return_entity_expr,
            query_kind="return",
        )

        retention_events = ast.SelectSetQuery.create_from_queries([start_event_query, return_event_query], "UNION ALL")

        select_fields: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["actor_id"])),
            ast.Alias(
                alias="start_event_timestamps",
                expr=parse_expr("arrayFlatten(groupArray(start_event_timestamps))"),
            ),
        ]

        # Property aggregation ignores minimum_occurrences (matching the legacy path), so the threshold filter only
        # applies to the events-only / data-warehouse return shapes. When it applies, the per-actor dupes the return
        # subquery emitted are flattened here, counted per interval, and intervals below the threshold are dropped.
        apply_minimum_occurrences = self.minimum_occurrences > 1 and not self.has_property_aggregation

        if apply_minimum_occurrences:
            select_fields.append(self._date_range_alias())
            select_fields.extend(
                self._get_minimum_occurrences_aliases(
                    minimum_occurrences=self.minimum_occurrences,
                    with_dupes_expr=parse_expr("arrayFlatten(groupArray(return_event_timestamps))"),
                )
            )
            select_fields.append(
                ast.Alias(
                    alias="return_event_timestamps",
                    expr=self._minimum_occurrences_return_timestamps_expr(self.minimum_occurrences),
                )
            )
        else:
            select_fields.append(
                ast.Alias(
                    alias="return_event_timestamps",
                    expr=parse_expr("arrayFlatten(groupArray(return_event_timestamps))"),
                )
            )
            select_fields.append(self._date_range_alias())

        if self.has_property_aggregation:
            select_fields.extend(
                [
                    ast.Alias(
                        alias="_start_event_data",
                        expr=parse_expr("arrayFlatten(groupArray(_start_event_data))"),
                    ),
                    ast.Alias(
                        alias="_return_event_data",
                        expr=parse_expr("arrayFlatten(groupArray(_return_event_data))"),
                    ),
                ]
            )

        select_fields.extend(
            [
                self._start_interval_index_alias_expr(is_valid_start_interval),
                ast.Alias(alias="intervals_from_base", expr=intervals_from_base_expr),
            ]
        )

        if retention_value_expr:
            select_fields.append(ast.Alias(alias="retention_value", expr=retention_value_expr))

        group_by_fields: list[ast.Expr] = [ast.Field(chain=["actor_id"])]
        if has_breakdown_filter(self.query.breakdownFilter):
            if self.is_first_ever_occurrence:
                # Each arm resolves the same single per-actor value; max() collapses the
                # UNION rows deterministically and lets a real value win over the
                # empty-bucket fallback on a data-warehouse-mixed series.
                select_fields.append(ast.Alias(alias="breakdown_value", expr=parse_expr("max(breakdown_value)")))
            else:
                # Per-value rows from the arms; carry the value as a grouping key so the
                # per-value cohort partitioning survives the outer aggregation.
                select_fields.append(ast.Alias(alias="breakdown_value", expr=ast.Field(chain=["breakdown_value"])))
                group_by_fields.append(ast.Field(chain=["breakdown_value"]))

        base_query = ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=retention_events, alias="retention_events"),
            group_by=group_by_fields,
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

        return base_query

    def _can_single_scan(self) -> bool:
        # Events-only, non-property-aggregating series read the same `events` source on both arms, so the
        # start and return timestamp arrays can be computed in one pass. Property aggregation has a known
        # legacy/variant discrepancy and stays on the UNION; a data-warehouse entity is a genuinely
        # different source and cannot collapse here.
        return (
            not self.has_property_aggregation
            and self.start_event.type != EntityType.DATA_WAREHOUSE
            and self.return_event.type != EntityType.DATA_WAREHOUSE
        )

    def _build_single_scan_query(
        self,
        start_interval_index_filter: int | None = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        # Source-parameterized so the deferred same-data-warehouse-table collapse is a small follow-up.
        # For the events-only case the source is the events table.
        timestamp_field = ast.Field(chain=["timestamp"])
        actor_field = ast.Field(chain=[self.aggregation_target_events_column])
        start_of_interval_sql = self.query_date_range.get_start_of_interval_hogql(source=timestamp_field)

        start_event_timestamps_expr = self._single_scan_start_event_timestamps_expr(
            timestamp_field, self.start_entity_expr
        )
        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            start_event_timestamps_expr = self._first_time_start_event_timestamps_expr(self.start_event)

        select_fields: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=actor_field),
            ast.Alias(alias="start_event_timestamps", expr=start_event_timestamps_expr),
            self._date_range_alias(),
        ]

        if self.minimum_occurrences > 1:
            select_fields.extend(
                self._get_minimum_occurrences_aliases(
                    minimum_occurrences=self.minimum_occurrences,
                    with_dupes_expr=self._get_dwh_return_timestamps_expr(
                        minimum_occurrences=self.minimum_occurrences,
                        start_of_interval_sql=start_of_interval_sql,
                        return_entity_expr=self.return_entity_expr,
                        timestamp_field=timestamp_field,
                    ),
                )
            )
            return_event_timestamps_expr = self._minimum_occurrences_return_timestamps_expr(self.minimum_occurrences)
        else:
            return_event_timestamps_expr = self._get_dwh_return_timestamps_expr(
                minimum_occurrences=1,
                start_of_interval_sql=start_of_interval_sql,
                return_entity_expr=self.return_entity_expr,
                timestamp_field=timestamp_field,
            )

        is_valid_start_interval = self._is_valid_start_interval_expr("_start_event_timestamps")
        intervals_from_base_expr, retention_value_expr = self._get_intervals_from_base_exprs()

        select_fields.extend(
            [
                ast.Alias(alias="return_event_timestamps", expr=return_event_timestamps_expr),
                self._start_interval_index_alias_expr(is_valid_start_interval),
                ast.Alias(alias="intervals_from_base", expr=intervals_from_base_expr),
            ]
        )

        if retention_value_expr:
            select_fields.append(ast.Alias(alias="retention_value", expr=retention_value_expr))

        return ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=self._event_filters()),
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

    def _single_scan_start_event_timestamps_expr(self, timestamp_field: ast.Expr, entity_expr: ast.Expr) -> ast.Expr:
        # The recurring within-window set of start-interval timestamps, one pass over the source. Mirrors the
        # inline aggregate the legacy path and the DWH start arm both build.
        start_of_interval_sql = self.query_date_range.get_start_of_interval_hogql(source=timestamp_field)
        return parse_expr(
            """
            arraySort(
                groupUniqArrayIf(
                    {start_of_interval_sql},
                    {entity_expr} and
                    {filter_timestamp}
                )
            )
            """,
            {
                "start_of_interval_sql": start_of_interval_sql,
                "entity_expr": entity_expr,
                "filter_timestamp": self.events_timestamp_filter(field=timestamp_field),
            },
        )

    def _start_interval_index_alias_expr(self, is_valid_start_interval: ast.Expr) -> ast.Alias:
        # Explodes the (0-based) indices of intervals whose start event matched, shared by the single-scan
        # and UNION-outer shapes. Reads the date_range and start_event_timestamps aliases from the same SELECT.
        return ast.Alias(
            alias="start_interval_index",
            expr=parse_expr(
                """
                arrayJoin(
                    arrayFilter(
                        x -> x > -1,
                        arrayMap(
                        (interval_index, interval_date, _start_event_timestamps) ->
                            if(
                                {is_valid_start_interval},
                                interval_index - 1,
                                -1
                            ),
                            arrayEnumerate(date_range),
                            date_range,
                            arrayResize(
                                [start_event_timestamps],
                                length(date_range),
                                start_event_timestamps
                            )
                        )
                    )
                )
            """,
                {"is_valid_start_interval": is_valid_start_interval},
            ),
        )

    def _build_dwh_retention_event_query(
        self,
        entity: RetentionEntity,
        legacy_entity_expr: ast.Expr,
        query_kind: Literal["start", "return"],
    ) -> ast.SelectQuery:
        entity_is_dwh = entity.type == EntityType.DATA_WAREHOUSE

        actor_column_name = entity.aggregation_target_field if entity_is_dwh else self.aggregation_target_events_column
        assert actor_column_name
        actor_field = ast.Field(chain=[actor_column_name])

        timestamp_column_name = entity.timestamp_field if entity_is_dwh else "timestamp"
        assert timestamp_column_name
        timestamp_field = ast.Field(chain=[timestamp_column_name])

        start_of_interval_sql = self.query_date_range.get_start_of_interval_hogql(source=timestamp_field)
        entity_expr = self._get_dwh_retention_entity_expr(entity=entity, legacy_entity_expr=legacy_entity_expr)

        start_event_timestamps_expr: ast.Expr
        return_event_timestamps_expr: ast.Expr
        start_event_data_expr: ast.Expr
        return_event_data_expr: ast.Expr

        if self.has_property_aggregation:
            event_data_expr = self._get_dwh_property_aggregation_event_data_expr(
                entity=entity,
                entity_expr=entity_expr,
                query_kind=query_kind,
                start_of_interval_sql=start_of_interval_sql,
                timestamp_field=timestamp_field,
            )
            timestamps_expr = parse_expr(
                "arraySort(arrayDistinct(arrayMap(x -> x.1, {event_data})))", {"event_data": event_data_expr}
            )
            if query_kind == "start":
                start_event_timestamps_expr = timestamps_expr
                return_event_timestamps_expr = ast.Array(exprs=[])
                start_event_data_expr = event_data_expr
                return_event_data_expr = ast.Array(exprs=[])
            else:
                start_event_timestamps_expr = ast.Array(exprs=[])
                return_event_timestamps_expr = timestamps_expr
                start_event_data_expr = ast.Array(exprs=[])
                return_event_data_expr = event_data_expr
        else:
            if query_kind == "start":
                start_event_timestamps_expr = self._single_scan_start_event_timestamps_expr(
                    timestamp_field, entity_expr
                )
                return_event_timestamps_expr = ast.Array(exprs=[])
            else:
                timestamps_expr = self._get_dwh_return_timestamps_expr(
                    minimum_occurrences=self.minimum_occurrences,
                    start_of_interval_sql=start_of_interval_sql,
                    return_entity_expr=entity_expr,
                    timestamp_field=timestamp_field,
                )
                start_event_timestamps_expr = ast.Array(exprs=[])
                return_event_timestamps_expr = timestamps_expr

        # First-time retention only affects the start side: replace the recurring set of within-window start
        # intervals with the single cohorting interval derived from the entity-polymorphic first-time anchor.
        # Mirrors the wrapping that build_base_query_legacy applies (lines below in this class).
        if query_kind == "start" and (self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence):
            start_event_timestamps_expr = self._first_time_start_event_timestamps_expr(entity)

        table_name = entity.table_name if entity_is_dwh else "events"
        assert table_name
        where_expr = None if entity_is_dwh else ast.And(exprs=self._event_filters())

        select_fields: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=actor_field),
            ast.Alias(alias="start_event_timestamps", expr=start_event_timestamps_expr),
            ast.Alias(alias="return_event_timestamps", expr=return_event_timestamps_expr),
        ]

        if self.has_property_aggregation:
            select_fields.extend(
                [
                    ast.Alias(alias="_start_event_data", expr=start_event_data_expr),
                    ast.Alias(alias="_return_event_data", expr=return_event_data_expr),
                ]
            )

        group_by_fields: list[ast.Expr] = [ast.Field(chain=["actor_id"])]

        breakdown_extract = self.breakdown_extract_expr_for_query()
        if breakdown_extract is not None:
            select_fields.append(
                ast.Alias(
                    alias="breakdown_value",
                    expr=self._dwh_breakdown_value_arm_expr(entity, breakdown_extract, timestamp_field, query_kind),
                )
            )
            # Recurring / first-time-matching mirrors the legacy per-value cohort
            # semantics: grouping each arm by breakdown_value filters its start and
            # return aggregations to events carrying that value. First-ever resolves a
            # single per-actor value (argMinIf), so it stays grouped by actor_id only.
            if not self.is_first_ever_occurrence:
                group_by_fields.append(ast.Field(chain=["breakdown_value"]))

        return ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
            where=where_expr,
            group_by=group_by_fields,
        )

    def _first_time_start_event_timestamps_expr(self, entity: RetentionEntity) -> ast.Expr:
        # The variant subquery is already GROUP BY actor_id, so the polymorphic first-time anchor (a minIf)
        # resolves to one cohorting timestamp per actor. Emit that single bucketed interval when the anchor falls
        # inside the query window, otherwise nothing. This mirrors the legacy
        # if(has(_start_event_timestamps, min_timestamp), _start_event_timestamps, []) wrapping: in first-time
        # mode the only element ever read is start_event_timestamps[1] (the minimum), so a single-element array is
        # equivalent. A null anchor (first-ever occurrence not matching filters) or an out-of-window anchor both
        # fail the window check and yield an empty array, excluding the actor.
        anchor_expr = self.get_first_time_anchor_expr(entity)
        return parse_expr(
            "if({within_window}, [{bucketed_anchor}], [])",
            {
                "within_window": self.events_timestamp_filter(field=anchor_expr),
                "bucketed_anchor": self.query_date_range.date_to_start_of_interval_hogql(anchor_expr),
            },
        )

    def _get_dwh_property_aggregation_event_data_expr(
        self,
        *,
        entity: RetentionEntity,
        entity_expr: ast.Expr,
        query_kind: Literal["start", "return"],
        start_of_interval_sql: ast.Expr,
        timestamp_field: ast.Expr,
    ) -> ast.Expr:
        property_aggregation_expr = self.runner.property_aggregation_expr_for_entity(entity)
        if query_kind == "start" and not self._start_and_return_entities_are_same():
            property_aggregation_expr = ast.Constant(value=0.0)

        assert property_aggregation_expr

        return parse_expr(
            """
            groupArrayIf(
                ({start_of_interval_sql}, {property_aggregation_expr}, {timestamp_field}),
                {entity_expr} and {filter_timestamp}
            )
            """,
            {
                "start_of_interval_sql": start_of_interval_sql,
                "property_aggregation_expr": property_aggregation_expr,
                "timestamp_field": timestamp_field,
                "entity_expr": entity_expr,
                "filter_timestamp": self.events_timestamp_filter(field=timestamp_field),
            },
        )

    def _get_dwh_retention_entity_expr(self, entity: RetentionEntity, legacy_entity_expr: ast.Expr) -> ast.Expr:
        if entity.type != EntityType.DATA_WAREHOUSE:
            return legacy_entity_expr

        if entity.properties:
            return property_to_expr(entity.properties, self.team)

        return ast.Constant(value=True)

    def _start_and_return_entities_are_same(self) -> bool:
        identity_fields = {"id", "type", "table_name", "timestamp_field", "properties"}
        return self.start_event.model_dump(mode="json", include=identity_fields) == self.return_event.model_dump(
            mode="json", include=identity_fields
        )

    # Original version of the fixed interval query.
    def build_base_query_legacy(
        self,
        start_interval_index_filter: int | None = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        start_of_interval_sql = self.query_date_range.get_start_of_interval_hogql(
            source=ast.Field(chain=["events", "timestamp"])
        )

        event_filters = self._event_filters()

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
                "filter_timestamp": self.events_timestamp_filter(),
            },
        )

        minimum_occurrences_aliases = self._get_minimum_occurrences_aliases(
            minimum_occurrences=self.minimum_occurrences,
            with_dupes_expr=parse_expr(
                """
                groupArrayIf(
                    {start_of_interval_timestamp},
                    {returning_entity_expr} and
                    {filter_timestamp}
                )
                """,
                {
                    "start_of_interval_timestamp": start_of_interval_sql,
                    "returning_entity_expr": self.return_entity_expr,
                    "filter_timestamp": self.events_timestamp_filter(),
                },
            ),
        )

        if self.has_property_aggregation:
            # For property aggregation, we need separate handling for start (interval 0) and return events (interval 1+).
            # Tuples are (interval_start, value, actual_timestamp); actual_timestamp is used when start and
            # return events differ to filter interval-0 return events that happen after the start event.
            #
            # These raw expressions are stored in return_event_values and added as named aliases (_start_event_data,
            # _return_event_data) in select_fields. All later references use ast.Field to those aliases instead of
            # inlining the groupArrayIf expressions. This prevents ClickHouse from creating a self-join on the events
            # table when these aggregations appear inside lambda functions (arrayFilter/arrayMap/arrayMin), which would
            # otherwise cause MEMORY_LIMIT_EXCEEDED on large datasets.
            assert self.property_aggregation_expr
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
                    "filter_timestamp": self.events_timestamp_filter(),
                },
            )
            return_event_data = self._get_return_event_timestamps_expr(
                minimum_occurrences=self.minimum_occurrences,
                start_of_interval_sql=start_of_interval_sql,
                return_entity_expr=self.return_entity_expr,
            )
            # Reference the pre-computed aliases rather than inlining the expressions again
            return_event_timestamps = parse_expr("arrayMap(x -> x.1, _return_event_data)")
            return_event_values = (start_event_data, return_event_data)
        else:
            return_event_timestamps = self._get_return_event_timestamps_expr(
                minimum_occurrences=self.minimum_occurrences,
                start_of_interval_sql=start_of_interval_sql,
                return_entity_expr=self.return_entity_expr,
            )
            return_event_values = None

        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            min_timestamp_inner_expr = self.get_first_time_anchor_expr(self.start_event)

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
        is_valid_start_interval = self._is_valid_start_interval_expr("_start_event_timestamps")
        retention_value_expr: ast.Expr | None
        intervals_from_base_expr, retention_value_expr = self._get_intervals_from_base_exprs()

        select_fields: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["events", self.aggregation_target_events_column])),
            # start events between date_from and date_to (represented by start of interval)
            # when TARGET_FIRST_TIME, also adds filter for start (target) event performed for first time
            ast.Alias(alias="start_event_timestamps", expr=start_event_timestamps),
            # get all intervals between date_from and date_to (represented by start of interval)
            self._date_range_alias(),
            *minimum_occurrences_aliases,
        ]

        # When using aggregation mode, add the grouped data arrays as named aliases BEFORE columns that reference them.
        # This ensures ClickHouse uses the pre-aggregated arrays rather than re-executing the groupArrayIf inside
        # lambda functions, which would otherwise trigger a self-join on the events table and exceed memory limits.
        if self.has_property_aggregation:
            assert return_event_values is not None
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
                                (interval_index, interval_date, _start_event_timestamps) ->
                                    if(
                                        {is_valid_start_interval},
                                        interval_index - 1,
                                        -1
                                    ),
                                    arrayEnumerate(date_range),
                                    date_range,
                                    arrayResize(
                                        [start_event_timestamps],
                                        length(date_range),
                                        start_event_timestamps
                                    )
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

    def _get_minimum_occurrences_aliases(self, minimum_occurrences: int, with_dupes_expr: ast.Expr) -> list[ast.Alias]:
        """
        Only include the following expressions when minimum occurrences value is set and greater than one. The query
        with occurrences uses slightly more RAM, what can make some existing queries go over the max memory setting we
        have and having them stop working.

        ``with_dupes_expr`` is the per-actor multiset of return-event interval starts (duplicates retained). The legacy
        single-query path builds it directly from the events table; the UNION ALL variant flattens the dupes already
        emitted by its return subquery. The downstream counts-per-interval logic is identical for both.
        """
        if minimum_occurrences == 1:
            return []

        return_event_timestamps_with_dupes = ast.Alias(
            alias="return_event_timestamps_with_dupes",
            expr=with_dupes_expr,
        )
        return_event_counts_by_interval = ast.Alias(
            alias="return_event_counts_by_interval",
            expr=parse_expr(
                """
                arrayMap(
                    (interval_date, _return_event_timestamps_with_dupes) ->
                        countEqual(_return_event_timestamps_with_dupes, interval_date),
                    date_range,
                    arrayResize(
                        [return_event_timestamps_with_dupes],
                        length(date_range),
                        return_event_timestamps_with_dupes
                    )
                )
                """
            ),
        )
        return [return_event_timestamps_with_dupes, return_event_counts_by_interval]

    def _minimum_occurrences_return_timestamps_expr(self, minimum_occurrences: int) -> ast.Expr:
        # Keep only the intervals where the actor had at least `minimum_occurrences` return events. Relies on the
        # date_range and return_event_counts_by_interval aliases (from _get_minimum_occurrences_aliases) being in
        # scope in the same SELECT.
        return parse_expr(
            """
            arrayFilter(
                (date, counts) -> counts >= {minimum_occurrences},
                date_range,
                return_event_counts_by_interval
            )
            """,
            {"minimum_occurrences": ast.Constant(value=minimum_occurrences)},
        )

    def _get_dwh_return_timestamps_expr(
        self,
        minimum_occurrences: int,
        start_of_interval_sql: ast.Expr,
        return_entity_expr: ast.Expr,
        timestamp_field: ast.Expr | None,
    ) -> ast.Expr:
        # The variant's return subquery is already grouped per actor. With a threshold of 1 we emit the deduped set of
        # return intervals. With a higher threshold we keep duplicates so the outer aggregation can count per-interval
        # occurrences and drop intervals below the threshold — the per-actor source for the legacy
        # return_event_timestamps_with_dupes alias.
        if minimum_occurrences > 1:
            return parse_expr(
                """
                groupArrayIf(
                    {start_of_interval_sql},
                    {return_entity_expr} and
                    {filter_timestamp}
                )
                """,
                {
                    "start_of_interval_sql": start_of_interval_sql,
                    "return_entity_expr": return_entity_expr,
                    "filter_timestamp": self.events_timestamp_filter(field=timestamp_field),
                },
            )

        return self._get_return_event_timestamps_expr(
            minimum_occurrences=1,
            start_of_interval_sql=start_of_interval_sql,
            return_entity_expr=return_entity_expr,
            timestamp_field=timestamp_field,
        )

    def _date_range_alias(self) -> ast.Alias:
        return ast.Alias(
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
        )

    def _event_filters(self) -> list[ast.Expr]:
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

        return event_filters

    def _is_valid_start_interval_expr(self, start_event_timestamps_field: str = "start_event_timestamps") -> ast.Expr:
        start_event_timestamps = ast.Field(chain=[start_event_timestamps_field])
        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            return parse_expr(
                "{start_event_timestamps}[1] = interval_date",
                {"start_event_timestamps": start_event_timestamps},
            )

        return parse_expr(
            "has({start_event_timestamps}, interval_date)",
            {"start_event_timestamps": start_event_timestamps},
        )

    def _is_first_interval_after_start_event_expr(self) -> ast.Expr:
        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            return parse_expr("start_event_timestamps[1] = date_range[start_interval_index + 1]")

        return parse_expr("has(start_event_timestamps, date_range[start_interval_index + 1])")

    def _get_intervals_from_base_exprs(self) -> tuple[ast.Expr, ast.Expr | None]:
        is_first_interval_after_start_event = self._is_first_interval_after_start_event_expr()
        intervals_from_base_array_aggregator = "arrayJoin"

        if self.has_property_aggregation:
            # _start_event_data and _return_event_data are added as aliases before intervals_from_base is selected.
            start_event_data_ref = ast.Field(chain=["_start_event_data"])
            return_event_data_ref = ast.Field(chain=["_return_event_data"])

            # When start and return events are different, aggregation values should come from the
            # return events only. Start events still add a zero-valued interval-0 marker so the
            # cohort count stays consistent with normal retention.
            # When they are the same event, start_data captures the interval-0 value and
            # return_data contributes only later intervals to avoid double-counting.
            different_event_entities = not self._start_and_return_entities_are_same()

            if different_event_entities:
                # Include return events in interval 0 (index 0 = same interval as cohort) only when
                # they happen strictly after the earliest start event in that interval.
                combined_data = parse_expr(
                    """
                    arrayConcat(
                        arrayFilter(
                            x -> x.1 >= 0,
                            arrayMap(
                                item -> (toInt(if(item.1 = date_range[start_interval_index + 1], 0, -1)), 0.0),
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

            return (
                parse_expr("(arrayJoin({data})).1", {"data": combined_data}),
                parse_expr("(arrayJoin({data})).2", {"data": combined_data}),
            )

        if self.is_custom_bracket_retention:
            bucket_logic = self._get_custom_bracket_intervals_from_base_expr()
            return (
                parse_expr(
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
                ),
                None,
            )

        return (
            self._get_default_intervals_from_base_expr(
                is_first_interval_after_start_event, intervals_from_base_array_aggregator
            ),
            None,
        )

    def _get_return_event_timestamps_expr(
        self,
        minimum_occurrences: int,
        start_of_interval_sql: ast.Expr,
        return_entity_expr: ast.Expr,
        timestamp_field: ast.Expr | None = None,
        property_aggregation_expr: ast.Expr | None = None,
    ) -> ast.Expr:
        if self.has_property_aggregation:
            assert self.property_aggregation_expr

            # Collect 3-tuples of (interval_start, value, actual_timestamp) for return events.
            # actual_timestamp is needed to filter same-interval return events that happen after the start event.
            actual_timestamp_field = timestamp_field or ast.Field(chain=["events", "timestamp"])
            property_expr = property_aggregation_expr or self.property_aggregation_expr
            assert property_expr
            return parse_expr(
                """
                groupArrayIf(
                    ({start_of_interval_timestamp}, {property_aggregation_expr}, {actual_timestamp_field}),
                    {returning_entity_expr} and
                    {filter_timestamp}
                )
                """,
                {
                    "start_of_interval_timestamp": start_of_interval_sql,
                    "property_aggregation_expr": property_expr,
                    "actual_timestamp_field": actual_timestamp_field,
                    "returning_entity_expr": return_entity_expr,
                    "filter_timestamp": self.events_timestamp_filter(field=timestamp_field),
                },
            )

        if minimum_occurrences > 1:
            return self._minimum_occurrences_return_timestamps_expr(minimum_occurrences)

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
                "filter_timestamp": self.events_timestamp_filter(field=timestamp_field),
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
