import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Optional, cast

from pydantic import BaseModel

from posthog.schema import GenericCachedQueryResponse, HogQLQueryModifiers, QueryStatus, QueryTiming

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.caching.utils import (
    ThresholdMode,
    cache_target_age as _cache_target_age,
)
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.utils import convert_property_value, flatten, relative_date_parse


class PropertyType(StrEnum):
    EVENT = "event"
    PERSON = "person"


class PropertyValuesQuery(BaseModel):
    kind: Literal["PropertyValuesQuery"] = "PropertyValuesQuery"
    property_type: PropertyType
    property_key: str
    search_value: Optional[str] = None
    event_names: Optional[list[str]] = None
    is_column: bool = False


class PropertyValueItem(BaseModel):
    name: Any
    count: Optional[int] = None


class PropertyValuesQueryResponse(BaseModel):
    results: list[PropertyValueItem]
    timings: Optional[list[QueryTiming]] = None
    hogql: Optional[str] = None
    modifiers: Optional[HogQLQueryModifiers] = None
    query_status: Optional[QueryStatus] = None


class CachedPropertyValuesQueryResponse(GenericCachedQueryResponse):
    results: list[PropertyValueItem]
    timings: Optional[list[QueryTiming]] = None
    hogql: Optional[str] = None
    modifiers: Optional[HogQLQueryModifiers] = None


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
        raise NotImplementedError("Person property values use raw SQL via _calculate_person()")

    def _calculate(self) -> PropertyValuesQueryResponse:
        if self.query.property_type == PropertyType.PERSON:
            return self._calculate_person()
        return self._calculate_event()

    def _calculate_event(self) -> PropertyValuesQueryResponse:
        result = execute_hogql_query(
            self._event_query(),
            team=self.team,
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

    def _calculate_person(self) -> PropertyValuesQueryResponse:
        # Use the raw SQL person query — the HogQL persons virtual table does full argMax dedup
        # which is correct but much slower (30s vs 4s on large teams). The raw SQL approximates
        # dedup with uniq(id) - uniqIf(id, is_deleted != 0) and caps at 100k rows, which is
        # fast enough and good enough for autocomplete.
        from posthog.queries.property_values import get_person_property_values_for_key

        rows = cast(
            list, get_person_property_values_for_key(self.query.property_key, self.team, self.query.search_value)
        )
        return PropertyValuesQueryResponse(
            results=self._format_person_results(rows),
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    def _event_query(self) -> ast.SelectQuery:
        from django.utils import timezone

        key = self.query.property_key
        chain: list[str | int] = [key] if self.query.is_column else ["properties", key]

        date_from = relative_date_parse("-7d", self.team.timezone_info).strftime("%Y-%m-%d 00:00:00")
        date_to = timezone.now().strftime("%Y-%m-%d 23:59:59")

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
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike,
                    left=ast.Call(name="toString", args=[ast.Field(chain=chain)]),
                    right=ast.Constant(value=f"%{self.query.search_value}%"),
                )
            )

        order_by: list[ast.OrderExpr] = (
            [
                ast.OrderExpr(
                    expr=ast.Call(name="length", args=[ast.Call(name="toString", args=[ast.Field(chain=chain)])]),
                    order="ASC",
                )
            ]
            if self.query.search_value
            else []
        )

        return ast.SelectQuery(
            select=[ast.Field(chain=chain)],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=conditions),
            order_by=order_by,
            limit=ast.Constant(value=10),
        )

    def _format_event_results(self, rows: list) -> list[PropertyValueItem]:
        values = []
        for row in rows:
            raw = row[0]
            if isinstance(raw, float | int | bool | uuid.UUID):
                values.append(raw)
            else:
                try:
                    values.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    values.append(raw)
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
