import json
import uuid
from datetime import datetime
from functools import cached_property
from typing import Optional, cast

from django.utils import timezone

import posthoganalytics

from posthog.schema import (
    CachedPropertyValuesQueryResponse,
    PropertyType,
    PropertyValueItem,
    PropertyValuesQuery,
    PropertyValuesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from posthog.caching.utils import (
    ThresholdMode,
    cache_target_age as _cache_target_age,
)
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import PropertyDefinition
from posthog.models.event.new_events_schema import use_new_events_schema
from posthog.queries.property_values import (
    get_event_property_values_from_aggregated_table,
    get_person_property_values_for_key,
)
from posthog.utils import convert_property_value, flatten, get_instance_region, relative_date_parse

from products.access_control.backend.property_access_control import get_restricted_property_names

PROPERTY_VALUES_TABLE_FLAG = "property-values-table"


class PropertyValuesQueryRunner(AnalyticsQueryRunner[PropertyValuesQueryResponse]):
    query: PropertyValuesQuery
    cached_response: CachedPropertyValuesQueryResponse

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        # Property values don't change frequently — treat as daily-interval data (6h staleness).
        # On cache miss the first request blocks; on stale cache the old results are returned immediately
        # and a background refresh is enqueued via RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS.
        if last_refresh is None:
            return None
        mode = ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT
        return _cache_target_age("day", last_refresh=last_refresh, mode=mode)

    def to_query(self) -> ast.SelectQuery:
        if self.query.property_type == PropertyType.EVENT:
            return self._event_query()
        # Person queries use raw SQL for speed (4s vs 30s) — move here when HogQL persons table gets faster
        raise NotImplementedError("Person property values use raw SQL via _calculate_person()")

    def _calculate(self) -> PropertyValuesQueryResponse:
        if self.query.property_type == PropertyType.PERSON:
            return self._calculate_person()
        return self._calculate_event()

    def _calculate_event(self) -> PropertyValuesQueryResponse:
        if self._is_restricted_event_property_key:
            return PropertyValuesQueryResponse(
                results=[],
                timings=self.timings.to_list(),
                modifiers=self.modifiers,
            )
        if self._use_property_values_table:
            return self._calculate_event_from_table()
        result = execute_hogql_query(
            self._event_query(),
            team=self.team,
            user=self.user,
            context=HogQLContext(
                team_id=self.team.pk,
                user=self.user,
                use_new_events_schema=self._use_new_events_schema,
            ),
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        return PropertyValuesQueryResponse(
            results=self._format_event_results(result.results),
            timings=self.timings.to_list(),
            hogql=result.hogql,
            modifiers=self.modifiers,
        )

    @cached_property
    def _is_restricted_event_property_key(self) -> bool:
        if self.query.is_column or self.query.property_key.startswith("$virt_"):
            return False
        return self.query.property_key in self._restricted_event_property_names

    @cached_property
    def _use_new_events_schema(self) -> bool:
        return use_new_events_schema(self.team.pk)

    @cached_property
    def _restricted_event_property_names(self) -> set[str]:
        return get_restricted_property_names(
            team_id=self.team.pk, user=self.user, property_type=PropertyDefinition.Type.EVENT
        )

    @cached_property
    def _use_property_values_table(self) -> bool:
        # Column and virtual lookups stay on the events scan: the table only
        # holds keys from the properties blob. event_names is deliberately not
        # a fallback: the table has no event dimension, so flagged teams get
        # event-agnostic value suggestions for event-scoped requests.
        if self.query.is_column or self.query.property_key.startswith("$virt_"):
            return False
        team_id = str(self.team.pk)
        if not posthoganalytics.feature_enabled(
            PROPERTY_VALUES_TABLE_FLAG,
            team_id,
            person_properties={"region": get_instance_region() or "DEV", "team_id": team_id},
            send_feature_flag_events=False,
        ):
            return False
        # Restricted keys stay on the events scan: the table read bypasses HogQL
        # property resolution, which is where property access control is enforced.
        # self.user is None on the events endpoint path, which fail-closes to the
        # events scan for any key restricted for anyone on the team.
        return self.query.property_key not in self._restricted_event_property_names

    def _calculate_event_from_table(self) -> PropertyValuesQueryResponse:
        rows = cast(
            list,
            get_event_property_values_from_aggregated_table(
                self.query.property_key, self.team, self.query.search_value
            ),
        )
        return PropertyValuesQueryResponse(
            results=self._format_table_results(rows),
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    def _calculate_person(self) -> PropertyValuesQueryResponse:
        # Use the raw SQL person query — the HogQL persons virtual table does full argMax dedup
        # which is correct but much slower (30s vs 4s on large teams). The raw SQL approximates
        # dedup with uniq(id) - uniqIf(id, is_deleted != 0) and caps at 100k rows, which is
        # fast enough and good enough for autocomplete.
        rows = cast(
            list, get_person_property_values_for_key(self.query.property_key, self.team, self.query.search_value)
        )
        return PropertyValuesQueryResponse(
            results=self._format_person_results(rows),
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    def _event_query(self) -> ast.SelectQuery:
        key = self.query.property_key
        is_virtual = key.startswith("$virt_")
        chain: list[str | int] = [key] if (self.query.is_column or is_virtual) else ["properties", key]
        field_expr: ast.Expr = ast.Field(chain=chain)
        value_expr: ast.Expr = (
            ast.Call(name="toJSONString", args=[field_expr]) if self._use_new_events_schema else field_expr
        )
        presence_expr: ast.Expr = field_expr
        string_expr: ast.Expr = ast.Call(name="toString", args=[field_expr])

        date_from = relative_date_parse("-7d", self.team.timezone_info).strftime("%Y-%m-%d 00:00:00")
        date_to = timezone.now().astimezone(self.team.timezone_info).strftime("%Y-%m-%d 23:59:59")

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
        ]
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=presence_expr,
                right=ast.Constant(value=None),
            )
        )

        if self.query.event_names:
            event_conditions: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=name),
                )
                for name in self.query.event_names
            ]
            conditions.append(ast.Or(exprs=event_conditions) if len(event_conditions) > 1 else event_conditions[0])

        if self.query.search_value:
            escaped = self.query.search_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike,
                    left=string_expr,
                    right=ast.Constant(value=f"%{escaped}%"),
                )
            )

        order_by: list[ast.OrderExpr] = (
            [
                ast.OrderExpr(
                    expr=ast.Call(name="length", args=[string_expr]),
                    order="ASC",
                )
            ]
            if self.query.search_value
            else []
        )

        return ast.SelectQuery(
            select=[value_expr],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=conditions),
            order_by=order_by,
            limit=ast.Constant(value=10),
        )

    def _format_event_results(self, rows: list) -> list[PropertyValueItem]:
        values: list[object] = []
        for row in rows:
            raw = row[0]
            if self._use_new_events_schema:
                values.append(json.loads(raw))
            elif isinstance(raw, float | int | bool | uuid.UUID):
                values.append(raw)
            else:
                # ClickHouse strips outer quotes from string values but leaves inner \" escapes,
                # so '["a","b"]' comes back as [\"a\",\"b\"] — unescape before parsing.
                cleaned = raw.replace('\\"', '"') if isinstance(raw, str) else raw
                try:
                    values.append(json.loads(cleaned))
                except (json.JSONDecodeError, TypeError):
                    values.append(cleaned)
        return self._to_property_value_items(values)

    def _format_table_results(self, rows: list) -> list[PropertyValueItem]:
        # Values are stored as the raw strings the aggregator coerced at fan-out, so
        # JSON-ish values (arrays, numbers, bools) parse and arrays flatten into
        # individual entries, matching the events-scan formatting. No '\\"' unescape
        # is needed on the legacy path since the table stores clean strings.
        values: list[object] = []
        for row in rows:
            raw = row[0]
            try:
                values.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                values.append(raw)
        return self._to_property_value_items(values)

    def _to_property_value_items(self, values: list[object]) -> list[PropertyValueItem]:
        return [PropertyValueItem(name=convert_property_value(v)) for v in flatten(values)]

    def _format_person_results(self, rows: list) -> list[PropertyValueItem]:
        results = []
        for row in rows:
            raw_value, count = row[0], row[1]
            try:
                name = convert_property_value(json.loads(raw_value))
            except (json.JSONDecodeError, TypeError):
                name = convert_property_value(raw_value)
            results.append(PropertyValueItem(name=name, count=int(count)))
        return results
