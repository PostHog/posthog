import json
import uuid
from datetime import datetime
from functools import cached_property
from typing import Any, Optional, cast

from django.conf import settings
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
from posthog.hogql.query import execute_hogql_query

from posthog.caching.utils import (
    ThresholdMode,
    cache_target_age as _cache_target_age,
)
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import PropertyDefinition
from posthog.queries.insight import insight_sync_execute
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
        if self._use_property_values_table:
            return self._calculate_event_from_table()
        if self._use_legacy_events_scan:
            return self._calculate_event_from_legacy_events()
        result = execute_hogql_query(
            self._event_query(),
            team=self.team,
            user=self.user,
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
    def _use_legacy_events_scan(self) -> bool:
        return (
            settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA
            and not self.query.is_column
            and not self.query.property_key.startswith("$virt_")
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
        restricted = get_restricted_property_names(
            team_id=self.team.pk, user=self.user, property_type=PropertyDefinition.Type.EVENT
        )
        return self.query.property_key not in restricted

    def _calculate_event_from_legacy_events(self) -> PropertyValuesQueryResponse:
        restricted = get_restricted_property_names(
            team_id=self.team.pk, user=self.user, property_type=PropertyDefinition.Type.EVENT
        )
        if self.query.property_key in restricted:
            return PropertyValuesQueryResponse(
                results=[],
                timings=self.timings.to_list(),
                modifiers=self.modifiers,
            )

        property_field = (
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(key)s), ''), 'null'), '^\"|\"$', '')"
        )
        date_from = relative_date_parse("-7d", self.team.timezone_info).strftime("%Y-%m-%d 00:00:00")
        date_to = timezone.now().astimezone(self.team.timezone_info).strftime("%Y-%m-%d 23:59:59")
        params: dict[str, Any] = {
            "team_id": self.team.pk,
            "key": self.query.property_key,
            "date_from": date_from,
            "date_to": date_to,
        }

        event_filter = ""
        if self.query.event_names:
            event_conditions = []
            for index, event_name in enumerate(self.query.event_names):
                event_conditions.append(f"events.event = %(event_{index})s")
                params[f"event_{index}"] = event_name
            event_filter = f"AND ({' OR '.join(event_conditions)})"

        value_filter = ""
        order_by = ""
        if self.query.search_value:
            escaped = self.query.search_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            value_filter = f"AND {property_field} ILIKE %(value)s"
            params["value"] = f"%{escaped}%"
            order_by = f"ORDER BY length({property_field}) ASC"

        query = f"""
SELECT DISTINCT {property_field} AS value
FROM events
WHERE and(
    equals(events.team_id, %(team_id)s),
    greaterOrEquals(events.timestamp, toDateTime64(%(date_from)s, 6, 'UTC')),
    lessOrEquals(events.timestamp, toDateTime64(%(date_to)s, 6, 'UTC')),
    isNotNull({property_field})
)
    {event_filter}
    {value_filter}
{order_by}
LIMIT 10
"""
        result = insight_sync_execute(
            query,
            params,
            query_type="get_property_values_with_value",
            team_id=self.team.pk,
        )
        return PropertyValuesQueryResponse(
            results=self._format_event_results(result),
            timings=self.timings.to_list(),
            hogql=query,
            modifiers=self.modifiers,
        )

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
        field_expr = ast.Field(chain=chain)
        presence_expr: ast.Expr = field_expr
        string_expr: ast.Expr = ast.Call(name="toString", args=[field_expr])
        use_native_property_subcolumn = (
            settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA and not self.query.is_column and not is_virtual
        )
        if use_native_property_subcolumn:
            presence_expr = ast.Call(name="isNotNull", args=[field_expr])
            string_expr = ast.Call(name="toString", args=[field_expr])

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
        if use_native_property_subcolumn:
            conditions.append(presence_expr)
        else:
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
            select=[field_expr],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=conditions),
            order_by=order_by,
            limit=ast.Constant(value=10),
        )

    def _format_event_results(self, rows: list) -> list[PropertyValueItem]:
        values: list[Any] = []
        for row in rows:
            raw = row[0]
            if isinstance(raw, float | int | bool | uuid.UUID):
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
        # is needed here since the table stores clean strings.
        values: list[Any] = []
        for row in rows:
            raw = row[0]
            try:
                values.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                values.append(raw)
        return self._to_property_value_items(values)

    def _to_property_value_items(self, values: list[Any]) -> list[PropertyValueItem]:
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
