"""
Personal LLM spend analysis endpoint.

Surfaces the requesting user's own LLM spend across PostHog products (last N
days) by running a fixed set of HogQL queries against PostHog's internal cloud
analytics team. Scoped to a single `ai_product` via the required `product`
query param; see `SUPPORTED_PRODUCTS` for the currently accepted values.

Endpoint:
- GET /api/llm_analytics/@me/spend/?product=<ai_product>&date_from=-30d&date_to=&limit=50&refresh=false&hourly=false
"""

from __future__ import annotations

import re
import hmac
import json
import time
import hashlib
import datetime
from typing import Any, cast
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpRequest, HttpResponseBase, HttpResponseRedirect

import requests
import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    WebhookSignatureAuthentication,
)
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team, User
from posthog.permissions import APIScopePermission
from posthog.rate_limit import PersonalSpendBurstThrottle, PersonalSpendDailyThrottle, PersonalSpendSustainedThrottle
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)

MAX_PRODUCT_KEY_LENGTH = 64
MAX_DATE_STRING_LENGTH = 32

SUPPORTED_PRODUCTS = frozenset({"posthog_code"})

DEFAULT_DATE_FROM = "-30d"
MAX_WINDOW_DAYS = 90
# The most calendar days a MAX_WINDOW_DAYS window can touch: partial days at both edges.
BY_DAY_MAX_ROWS = MAX_WINDOW_DAYS + 1
# Hourly series are only useful (and cheap) over short windows; a "last 24h" or
# "last few days" view is the intended consumer.
BY_HOUR_MAX_WINDOW_DAYS = 8
# Partial hours at both edges, same reasoning as BY_DAY_MAX_ROWS.
BY_HOUR_MAX_ROWS = BY_HOUR_MAX_WINDOW_DAYS * 24 + 1
_RELATIVE_DATE_RE = re.compile(r"^-?\d+[hdwmqyHDWMQY](Start|End)?$")

MIN_LIMIT = 1
MAX_LIMIT = 200
DEFAULT_LIMIT = 50

CACHE_TIMEOUT_SECONDS = 300

UTC = ZoneInfo("UTC")


def _internal_team_id() -> int:
    return settings.LLM_ANALYTICS_INTERNAL_TEAM_ID


def _cache_key(email: str, date_from: str, date_to: str | None, product: str, limit: int, hourly: bool) -> str:
    to_slot = date_to or "_now"
    return f"personal_spend:{email}:{date_from}:{to_slot}:{product}:{limit}:{int(hourly)}"


def _parse_date_param(value: str, field: str, now: datetime.datetime) -> datetime.datetime:
    """Accepts either an ISO date / datetime or a relative shorthand like `-7d`. Rejects garbage."""
    looks_relative = _RELATIVE_DATE_RE.match(value) is not None
    looks_iso = value[:1].isdigit()
    if not (looks_relative or looks_iso):
        raise exceptions.ValidationError(
            {
                field: f"Could not parse `{value}`. Use an ISO date (e.g. `2026-04-23`) or relative shorthand (e.g. `-7d`)."
            }
        )
    try:
        return relative_date_parse(value, UTC, now=now)
    except Exception as exc:
        raise exceptions.ValidationError({field: f"Could not parse `{value}`: {exc}"})


def _resolve_window(date_from: str, date_to: str | None) -> tuple[datetime.datetime, datetime.datetime]:
    """Resolve relative or absolute date strings to UTC datetimes, capped at MAX_WINDOW_DAYS."""
    now = datetime.datetime.now(UTC)
    from_dt = _parse_date_param(date_from, "date_from", now)
    to_dt = _parse_date_param(date_to, "date_to", now) if date_to else now

    if to_dt <= from_dt:
        raise exceptions.ValidationError({"date_to": "Must be later than `date_from`."})
    if (to_dt - from_dt).total_seconds() > MAX_WINDOW_DAYS * 86400:
        raise exceptions.ValidationError(
            {"date_from": f"Window between `date_from` and `date_to` cannot exceed {MAX_WINDOW_DAYS} days."}
        )
    return from_dt, to_dt


class _SpendQueryParamsSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        default=DEFAULT_DATE_FROM,
        max_length=MAX_DATE_STRING_LENGTH,
        help_text=(
            "Start of the spend window. Accepts absolute dates (`2026-04-23`) or relative strings "
            "(`-7d`, `-1m`, etc.) — same parser used elsewhere in PostHog. Defaults to `-30d`. The "
            "window between `date_from` and `date_to` cannot exceed 90 days."
        ),
    )
    date_to = serializers.CharField(
        required=False,
        default=None,
        allow_null=True,
        max_length=MAX_DATE_STRING_LENGTH,
        help_text=("End of the spend window. Accepts the same formats as `date_from`. Defaults to `now` when omitted."),
    )
    product = serializers.CharField(
        required=True,
        allow_null=False,
        allow_blank=False,
        max_length=MAX_PRODUCT_KEY_LENGTH,
        help_text=(
            "Required `ai_product` key to scope the tool / model / trace breakdowns to a single product. "
            f"Only the following products are currently supported: {', '.join(sorted(SUPPORTED_PRODUCTS))}."
        ),
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=MIN_LIMIT,
        max_value=MAX_LIMIT,
        default=DEFAULT_LIMIT,
        help_text=(
            f"Maximum number of rows to return per breakdown ({MIN_LIMIT}-{MAX_LIMIT}, defaults to {DEFAULT_LIMIT}). "
            "Each breakdown returns up to this many rows ordered by cost descending. "
            "Per-breakdown `truncated: true` indicates more rows exist beyond the limit."
        ),
    )
    refresh = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, bypass the result cache and re-run the underlying queries against ClickHouse.",
    )
    hourly = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "If true, additionally return a `by_hour` breakdown: an hour-ascending UTC cost series for the "
            "scoped product, with per-hour cost split into uncached input / output / cache read / cache "
            "creation components plus the matching token sums. Only allowed for windows of "
            f"{BY_HOUR_MAX_WINDOW_DAYS} days or less."
        ),
    )

    def validate_product(self, value: str) -> str:
        if value not in SUPPORTED_PRODUCTS:
            logger.warning("personal_spend.product_rejected", product=value)
            raise serializers.ValidationError(
                f"product `{value}` is not supported. Supported products: {', '.join(sorted(SUPPORTED_PRODUCTS))}."
            )
        return value


class _ProductBreakdownRowSerializer(serializers.Serializer):
    product = serializers.CharField(
        allow_null=True,
        help_text="Value of the `ai_product` property on the event (e.g. `posthog_code`, `background_agents`). Null when unset.",
    )
    event_count = serializers.IntegerField(
        help_text="Number of $ai_generation + $ai_embedding events for this product."
    )
    cost_usd = serializers.FloatField(help_text="Total cost in USD for this product over the lookback window.")


class _ToolBreakdownRowSerializer(serializers.Serializer):
    tool = serializers.CharField(
        allow_null=True,
        help_text=(
            "Individual tool name from `$ai_tools_called` (split on `,` since multi-tool generations "
            "store a comma-separated list). Null = pure text response with no tool call."
        ),
    )
    generation_count = serializers.IntegerField(
        help_text="Number of $ai_generation events whose tool list includes this tool."
    )
    cost_usd = serializers.FloatField(
        help_text=(
            "Sum of `$ai_total_cost_usd` for generations whose tool list includes this tool. Multi-tool "
            "generations contribute their full cost to every tool they invoked, so this sum can exceed "
            "`summary.scoped_cost_usd`. Prefer `share_of_scoped` for headline percentages — it's computed "
            "per row and doesn't require the totals to reconcile."
        ),
    )
    share_of_scoped = serializers.FloatField(
        help_text=(
            "This tool's share of `summary.scoped_cost_usd`, expressed as a float in `[0, 1]`. Independent "
            "per row, so co-occurring tools can each show a substantial share — the headline number to "
            "present (e.g. `'Bash drove 47% of your spend'`)."
        ),
    )
    avg_input_tokens = serializers.FloatField(
        help_text="Average `$ai_input_tokens` across these generations — high values signal context bloat per call.",
    )


class _ModelBreakdownRowSerializer(serializers.Serializer):
    model = serializers.CharField(allow_null=True, help_text="Value of the `$ai_model` property.")
    generation_count = serializers.IntegerField(help_text="Number of $ai_generation + $ai_embedding events.")
    cost_usd = serializers.FloatField(help_text="Total cost in USD for this model.")
    input_tokens = serializers.IntegerField(help_text="Sum of `$ai_input_tokens` for this model.")
    output_tokens = serializers.IntegerField(help_text="Sum of `$ai_output_tokens` for this model.")


class _DayBreakdownRowSerializer(serializers.Serializer):
    day = serializers.DateField(help_text="UTC calendar day the events fall on (`toDate(timestamp)`).")
    event_count = serializers.IntegerField(
        help_text="Number of $ai_generation + $ai_embedding events on this day for the scoped product."
    )
    cost_usd = serializers.FloatField(help_text="Total cost in USD on this day for the scoped product.")


class _HourBreakdownRowSerializer(serializers.Serializer):
    hour = serializers.DateTimeField(help_text="UTC hour bucket the events fall in (`toStartOfHour(timestamp)`).")
    event_count = serializers.IntegerField(
        help_text="Number of $ai_generation + $ai_embedding events in this hour for the scoped product."
    )
    cost_usd = serializers.FloatField(
        help_text=(
            "Total cost in USD in this hour (sum of `$ai_total_cost_usd`). Authoritative: the component "
            "columns below can sum to less than this when the cost breakdown was unavailable for some "
            "events — render any remainder as uncategorized rather than assuming the components reconcile."
        )
    )
    input_cost_usd = serializers.FloatField(
        help_text="Cost of uncached (full-price) input tokens in USD (sum of `$ai_input_cost_usd`)."
    )
    output_cost_usd = serializers.FloatField(help_text="Cost of output tokens in USD (sum of `$ai_output_cost_usd`).")
    cache_read_cost_usd = serializers.FloatField(
        help_text="Cost of prompt-cache reads in USD (sum of `$ai_cache_read_cost_usd`)."
    )
    cache_creation_cost_usd = serializers.FloatField(
        help_text=(
            "Cost of prompt-cache writes in USD (sum of `$ai_cache_creation_cost_usd`). A spike here with "
            "near-zero cache reads is the signature of a cold session being revived: the full conversation "
            "context is re-written to the cache at the cache-write rate instead of being read back cheaply."
        )
    )
    input_tokens = serializers.IntegerField(help_text="Sum of uncached `$ai_input_tokens` in this hour.")
    output_tokens = serializers.IntegerField(help_text="Sum of `$ai_output_tokens` in this hour.")
    cache_read_input_tokens = serializers.IntegerField(
        help_text="Sum of `$ai_cache_read_input_tokens` (prompt tokens served from cache) in this hour."
    )
    cache_creation_input_tokens = serializers.IntegerField(
        help_text="Sum of `$ai_cache_creation_input_tokens` (prompt tokens written to cache) in this hour."
    )


class _TopTraceRowSerializer(serializers.Serializer):
    trace_id = serializers.CharField(
        allow_null=True,
        help_text=(
            "`$ai_trace_id` of the session — opaque string scoped to the originating product. Format is "
            "not stable: most are UUIDs but some SDK wrappers emit JSON-shaped strings like "
            '`{"device_id":"...","session_id":"..."}`. Callers should treat this as an opaque '
            "identifier (URL-encode before linking to a trace view)."
        ),
    )
    generation_count = serializers.IntegerField(help_text="Number of $ai_generation events in this trace.")
    cost_usd = serializers.FloatField(help_text="Total cost in USD for this trace.")
    started_at = serializers.DateTimeField(allow_null=True, help_text="Timestamp of the earliest event in this trace.")


class _SummarySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        help_text="Inclusive UTC start of the spend window resolved from the request."
    )
    date_to = serializers.DateTimeField(help_text="Exclusive UTC end of the spend window resolved from the request.")
    product = serializers.CharField(
        help_text="The `ai_product` filter applied to tool / model / trace breakdowns — echoes the request `product`.",
    )
    total_cost_usd = serializers.FloatField(
        help_text="Total LLM cost in USD across every `ai_product` for the user — independent of the `product` filter."
    )
    event_count = serializers.IntegerField(
        help_text="Total $ai_generation + $ai_embedding events captured across every product."
    )
    scoped_cost_usd = serializers.FloatField(
        help_text=(
            "Total cost in USD for the product filter. Matches the cost summed across `by_tool` / `by_model` "
            "for the scoped slice."
        ),
    )
    scoped_event_count = serializers.IntegerField(
        help_text="Total $ai_generation + $ai_embedding events for the scoped slice."
    )


class _ErrorResponseSerializer(serializers.Serializer):
    """DRF's default error envelope — `{ "detail": str }` — typed for the OpenAPI schema."""

    detail = serializers.CharField(help_text="Human-readable error description from DRF.")


class _ProductBreakdownSerializer(serializers.Serializer):
    items = _ProductBreakdownRowSerializer(many=True, help_text="Rows of spend by product, ordered by cost descending.")
    truncated = serializers.BooleanField(
        help_text="True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them."
    )


class _ToolBreakdownSerializer(serializers.Serializer):
    items = _ToolBreakdownRowSerializer(many=True, help_text="Rows of spend by tool, ordered by cost descending.")
    truncated = serializers.BooleanField(
        help_text="True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them."
    )


class _ModelBreakdownSerializer(serializers.Serializer):
    items = _ModelBreakdownRowSerializer(many=True, help_text="Rows of spend by model, ordered by cost descending.")
    truncated = serializers.BooleanField(
        help_text="True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them."
    )


class _DayBreakdownSerializer(serializers.Serializer):
    items = _DayBreakdownRowSerializer(
        many=True,
        help_text=(
            "One row per UTC day that has events, ordered by day ascending. Days with no events are "
            "omitted — zero-fill client-side when rendering a continuous series."
        ),
    )
    truncated = serializers.BooleanField(
        help_text=(
            "Effectively always false: `by_day` ignores `limit` because truncating a time series by "
            f"cost would be meaningless, and the {MAX_WINDOW_DAYS}-day window cap already bounds the "
            "series length."
        )
    )


class _HourBreakdownSerializer(serializers.Serializer):
    items = _HourBreakdownRowSerializer(
        many=True,
        help_text=(
            "One row per UTC hour that has events, ordered by hour ascending. Hours with no events are "
            "omitted — zero-fill client-side when rendering a continuous series."
        ),
    )
    truncated = serializers.BooleanField(
        help_text=(
            "Effectively always false: `by_hour` ignores `limit` because truncating a time series by "
            f"cost would be meaningless, and the {BY_HOUR_MAX_WINDOW_DAYS}-day window cap already bounds "
            "the series length."
        )
    )


class _TopTracesSerializer(serializers.Serializer):
    items = _TopTraceRowSerializer(many=True, help_text="Rows of top traces by cost, ordered by cost descending.")
    truncated = serializers.BooleanField(
        help_text="True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them."
    )


class PersonalSpendAnalysisResponseSerializer(serializers.Serializer):
    """Structured personal LLM spend analysis for the requesting user."""

    summary = _SummarySerializer(help_text="High-level totals for the lookback window.")
    by_product = _ProductBreakdownSerializer(
        help_text="Spend grouped by the `ai_product` property — always across all products, never filtered."
    )
    by_tool = _ToolBreakdownSerializer(help_text="Spend grouped by tool. Scoped to `product` when set.")
    by_model = _ModelBreakdownSerializer(help_text="Spend grouped by `$ai_model`. Scoped to `product` when set.")
    by_day = _DayBreakdownSerializer(
        help_text="Spend grouped by UTC day, ordered ascending. Scoped to `product`. Not subject to `limit`."
    )
    by_hour = _HourBreakdownSerializer(
        required=False,
        help_text=(
            "Spend grouped by UTC hour with per-hour cost/token components, ordered ascending. Scoped to "
            "`product`. Only present when the request set `hourly=true`."
        ),
    )
    top_traces = _TopTracesSerializer(
        help_text=(
            "Deprecated — always returns `{items: [], truncated: false}`. Trace IDs are opaque strings "
            "that aren't actionable in the UI. Kept in the response shape so existing consumers don't "
            "crash; remove your rendering of this field and we'll drop it from the response entirely "
            "in a follow-up."
        )
    )


def _email_filter(email: str) -> ast.Expr:
    # With person-on-events, the event row carries `person_id` directly; HogQL then joins to
    # `person` to read `properties.email`. The join is bounded to one person per event (not a
    # full pdi walk), and on the main cluster the printer transparently uses the materialized
    # `pmat_email` column when registered. Same shape the AI observability "Users" tab uses
    # against `events` -- see `products/ai_observability/frontend/tabs/aiObservabilityUsersLogic.ts`.
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["person", "properties", "email"]),
        right=ast.Constant(value=email),
    )


def _timestamp_filter(from_dt: datetime.datetime, to_dt: datetime.datetime) -> ast.Expr:
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=from_dt),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=to_dt),
            ),
        ]
    )


def _event_in(events: list[str]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(exprs=[ast.Constant(value=e) for e in events]),
    )


def _ai_product_eq(value: str) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["properties", "ai_product"]),
        right=ast.Constant(value=value),
    )


def _product_filter(product: str) -> ast.Expr:
    return _ai_product_eq(product)


def _truncate(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Trim a `limit + 1` row fetch back down to `limit` rows and set the `truncated` flag."""
    return {"items": rows[:limit], "truncated": len(rows) > limit}


def _fetch_summary(
    team: Team, email: str, from_dt: datetime.datetime, to_dt: datetime.datetime, product: str
) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            countIf({product_filter}) AS scoped_event_count,
            round(sumIf(toFloat(properties.$ai_total_cost_usd), {product_filter}), 6) AS scoped_cost_usd,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS total_cost_usd
        FROM events
        WHERE {event_in} AND {email_filter} AND {timestamp_filter}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "product_filter": _product_filter(product),
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(from_dt, to_dt),
        },
        team=team,
        query_type="PersonalSpendSummary",
    )
    row = (result.results or [(0, 0.0, 0, 0.0)])[0]
    return {
        "date_from": from_dt,
        "date_to": to_dt,
        "product": product,
        "scoped_event_count": int(row[0] or 0),
        "scoped_cost_usd": float(row[1] or 0.0),
        "event_count": int(row[2] or 0),
        "total_cost_usd": float(row[3] or 0.0),
    }


def _fetch_by_product(
    team: Team, email: str, from_dt: datetime.datetime, to_dt: datetime.datetime, limit: int
) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            properties.ai_product AS product,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd
        FROM events
        WHERE {event_in} AND {email_filter} AND {timestamp_filter}
        GROUP BY product
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(from_dt, to_dt),
            "limit": ast.Constant(value=limit + 1),
        },
        team=team,
        query_type="PersonalSpendByProduct",
    )
    rows = [
        {
            "product": row[0] if row[0] is not None else None,
            "event_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, limit)


def _fetch_by_tool(
    team: Team,
    email: str,
    from_dt: datetime.datetime,
    to_dt: datetime.datetime,
    product: str,
    limit: int,
) -> dict[str, Any]:
    # `$ai_tools_called` stores a comma-separated list of all tools called within a
    # generation (e.g. "Bash,Read"). Split it so multi-tool generations contribute to
    # each individual tool row. nullIf restores the no-tool case (where the property
    # is NULL and coalesce produces an empty string) to a NULL bucket.
    query = parse_select(
        """
        SELECT
            nullIf(arrayJoin(splitByChar(',', coalesce(properties.$ai_tools_called, ''))), '') AS tool,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            round(avg(toFloat(properties.$ai_input_tokens)), 0) AS avg_input_tokens
        FROM events
        WHERE equals(event, '$ai_generation')
            AND {product_filter}
            AND {email_filter}
            AND {timestamp_filter}
        GROUP BY tool
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "product_filter": _product_filter(product),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(from_dt, to_dt),
            "limit": ast.Constant(value=limit + 1),
        },
        team=team,
        query_type="PersonalSpendByTool",
    )
    rows = [
        {
            "tool": row[0] if row[0] is not None else None,
            "generation_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "avg_input_tokens": float(row[3] or 0.0),
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, limit)


def _fetch_by_model(
    team: Team,
    email: str,
    from_dt: datetime.datetime,
    to_dt: datetime.datetime,
    product: str,
    limit: int,
) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            properties.$ai_model AS model,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
            sum(toFloat(properties.$ai_output_tokens)) AS output_tokens
        FROM events
        WHERE {event_in}
            AND {product_filter}
            AND {email_filter}
            AND {timestamp_filter}
        GROUP BY model
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "product_filter": _product_filter(product),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(from_dt, to_dt),
            "limit": ast.Constant(value=limit + 1),
        },
        team=team,
        query_type="PersonalSpendByModel",
    )
    rows = [
        {
            "model": row[0] if row[0] is not None else None,
            "generation_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "input_tokens": int(row[3] or 0),
            "output_tokens": int(row[4] or 0),
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, limit)


def _fetch_by_day(
    team: Team,
    email: str,
    from_dt: datetime.datetime,
    to_dt: datetime.datetime,
    product: str,
) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            toDate(timestamp) AS day,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd
        FROM events
        WHERE {event_in}
            AND {product_filter}
            AND {email_filter}
            AND {timestamp_filter}
        GROUP BY day
        ORDER BY day ASC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "product_filter": _product_filter(product),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(from_dt, to_dt),
            # Not the request `limit`: truncating a time series by cost makes no sense, and the
            # window cap already bounds the row count. +1 is the truncation probe row.
            "limit": ast.Constant(value=BY_DAY_MAX_ROWS + 1),
        },
        team=team,
        # HogQL wraps `timestamp` in the team's configurable timezone by default, which would
        # shift the day buckets; days here are documented as UTC, so pin them.
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        query_type="PersonalSpendByDay",
    )
    rows = [
        {
            "day": row[0],
            "event_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, BY_DAY_MAX_ROWS)


def _fetch_by_hour(
    team: Team,
    email: str,
    from_dt: datetime.datetime,
    to_dt: datetime.datetime,
    product: str,
) -> dict[str, Any]:
    # Cost components come from LiteLLM's cost_breakdown forwarded by the LLM gateway
    # ($ai_input_cost_usd is uncached input only — cache read/creation are priced
    # separately). Events that went through the token-estimation fallback carry only
    # $ai_total_cost_usd, so the components can undershoot cost_usd; the serializer
    # help_text tells clients to render the remainder as uncategorized.
    query = parse_select(
        """
        SELECT
            toStartOfHour(timestamp) AS hour,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            round(sum(toFloat(properties.$ai_input_cost_usd)), 6) AS input_cost_usd,
            round(sum(toFloat(properties.$ai_output_cost_usd)), 6) AS output_cost_usd,
            round(sum(toFloat(properties.$ai_cache_read_cost_usd)), 6) AS cache_read_cost_usd,
            round(sum(toFloat(properties.$ai_cache_creation_cost_usd)), 6) AS cache_creation_cost_usd,
            sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
            sum(toFloat(properties.$ai_output_tokens)) AS output_tokens,
            sum(toFloat(properties.$ai_cache_read_input_tokens)) AS cache_read_input_tokens,
            sum(toFloat(properties.$ai_cache_creation_input_tokens)) AS cache_creation_input_tokens
        FROM events
        WHERE {event_in}
            AND {product_filter}
            AND {email_filter}
            AND {timestamp_filter}
        GROUP BY hour
        ORDER BY hour ASC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "product_filter": _product_filter(product),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(from_dt, to_dt),
            # Not the request `limit` — same reasoning as by_day. +1 is the truncation probe row.
            "limit": ast.Constant(value=BY_HOUR_MAX_ROWS + 1),
        },
        team=team,
        # Hours are documented as UTC; pin them like by_day does.
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        query_type="PersonalSpendByHour",
    )
    rows = [
        {
            "hour": row[0],
            "event_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "input_cost_usd": float(row[3] or 0.0),
            "output_cost_usd": float(row[4] or 0.0),
            "cache_read_cost_usd": float(row[5] or 0.0),
            "cache_creation_cost_usd": float(row[6] or 0.0),
            "input_tokens": int(row[7] or 0),
            "output_tokens": int(row[8] or 0),
            "cache_read_input_tokens": int(row[9] or 0),
            "cache_creation_input_tokens": int(row[10] or 0),
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, BY_HOUR_MAX_ROWS)


def _compute_spend_analysis(
    *,
    email: str,
    date_from: str,
    date_to: str | None,
    product: str,
    limit: int,
    refresh: bool,
    hourly: bool,
) -> dict[str, Any]:
    """Cached, email-scoped spend analysis shared by the US viewset and the
    cross-region receiver. Expects already-validated params."""
    from_dt, to_dt = _resolve_window(date_from, date_to)
    if hourly and (to_dt - from_dt).total_seconds() > BY_HOUR_MAX_WINDOW_DAYS * 86400:
        raise exceptions.ValidationError(
            {"hourly": f"Hourly breakdown is only available for windows of {BY_HOUR_MAX_WINDOW_DAYS} days or less."}
        )

    cache_key = _cache_key(email, date_from, date_to, product, limit, hourly)

    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    team_id = _internal_team_id()
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        logger.exception("personal_spend.team_missing", team_id=team_id)
        raise exceptions.NotFound("Internal analytics team is not provisioned on this deployment.")

    # Tag the underlying ClickHouse reads with the LLM_ANALYTICS product so they show up
    # in the existing per-product Prometheus + cost-attribution dashboards alongside the
    # rest of AI observability traffic. Wraps every call into `_fetch_*` -> HogQL.
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team_id):
        summary = _fetch_summary(team, email, from_dt, to_dt, product)
        by_tool = _fetch_by_tool(team, email, from_dt, to_dt, product, limit)
        scoped = summary["scoped_cost_usd"] or 0.0
        # `cost_usd` in by_tool can exceed scoped_cost_usd because multi-tool generations
        # contribute to every tool. `share_of_scoped` is independent per row, so agents can
        # present headline percentages directly without reconciling sums.
        for row in by_tool["items"]:
            row["share_of_scoped"] = (row["cost_usd"] / scoped) if scoped > 0 else 0.0

        payload = {
            "summary": summary,
            "by_product": _fetch_by_product(team, email, from_dt, to_dt, limit),
            "by_tool": by_tool,
            "by_model": _fetch_by_model(team, email, from_dt, to_dt, product, limit),
            "by_day": _fetch_by_day(team, email, from_dt, to_dt, product),
            **({"by_hour": _fetch_by_hour(team, email, from_dt, to_dt, product)} if hourly else {}),
            # Deprecated — trace IDs are opaque and unactionable in the UI. Returned empty so
            # existing consumers don't crash while they remove the rendering. Drop the field
            # entirely once no consumer reads it.
            "top_traces": {"items": [], "truncated": False},
        }

    response_data = PersonalSpendAnalysisResponseSerializer(payload).data
    cache.set(cache_key, response_data, timeout=CACHE_TIMEOUT_SECONDS)
    return response_data


class _PersonalSpendUserViewSet(viewsets.ViewSet):
    """Base with the auth surface shared by the US viewset and the EU proxy so
    the regions stay indistinguishable to clients. The US internal receiver
    relies on this EU-side throttling as its only rate limit."""

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, APIScopePermission]
    # Identity-scoped (`/@me/...`): the caller reads their own spend, not data
    # nested under a team or project. `scope_object = "user"` matches the shape
    # of `/api/users/@me/` — APIScopePermission already exempts the `user`
    # bucket from team/org scoping, so we don't need
    # `dangerously_skip_scoped_team_enforcement` here. `user:read` is a clean
    # superset of "read your own spend": anyone trusted with `user:read`
    # already learns the more sensitive identity facts on `/api/users/@me/`,
    # and the wildcard `*` plus OAuth identity tokens (MCP) inherit access
    # the same way they do for every other `user`-scoped endpoint.
    scope_object = "user"
    throttle_classes = [PersonalSpendBurstThrottle, PersonalSpendSustainedThrottle, PersonalSpendDailyThrottle]

    def _require_email(self, request: Request) -> str:
        email = cast(User, request.user).email
        if not email:
            raise exceptions.PermissionDenied("User has no email on record; cannot scope spend analysis.")
        return email


class PersonalSpendViewSet(_PersonalSpendUserViewSet):
    """
    Returns the requesting user's personal LLM spend analysis across PostHog products.

    Queries are run server-side against PostHog's internal analytics team
    (settings.LLM_ANALYTICS_INTERNAL_TEAM_ID) and are strictly scoped to the
    authenticated user's email (read off the events row via person-on-events) —
    callers cannot pivot to other users' data. Authorization model is "any
    authenticated PostHog user may read their own spend" via `user:read` (the
    same scope that covers `/api/users/@me/`). Queries the shared `events`
    table directly -- same pattern as the LLM Analytics "Users" tab and every
    other person-property filter on AI events. We don't route through
    `query_ai_events` because the satellite `ai_events`
    cluster's Distributed `person` shim doesn't declare materialized columns
    like `pmat_email`, and the helper's fallback only catches empty results,
    not the unresolved-identifier exception that would fire there. The
    `events`-table WHERE clauses lead with the sort-key columns (`team_id`,
    `event`, `timestamp`) so the scan narrows before the person join fires,
    and the HogQL printer uses `pmat_email` on the main cluster's `person`
    when registered -- so this path should be comparable to what the
    satellite would have served. The endpoint is cached for 5 minutes per
    user (see `CACHE_TIMEOUT_SECONDS`). The `product` query param is required
    and scopes tool / model / trace breakdowns to a single `ai_product`; see
    `SUPPORTED_PRODUCTS` for the currently accepted values. `by_product` always
    returns the full cross-product breakdown. The endpoint is only registered
    on US Cloud + dev/test envs; hobby / self-hosted deploys never see this
    URL; EU deploys serve it via `PersonalSpendEUProxyViewSet` (or a 302 to
    the US URL while the cross-region secret is unprovisioned).
    """

    @extend_schema(
        operation_id="llm_analytics_personal_spend_list",
        parameters=[_SpendQueryParamsSerializer],
        responses={
            200: PersonalSpendAnalysisResponseSerializer,
            400: _ErrorResponseSerializer,
            401: _ErrorResponseSerializer,
            403: _ErrorResponseSerializer,
            404: _ErrorResponseSerializer,
            429: _ErrorResponseSerializer,
        },
        description=(
            "Return a structured personal LLM spend analysis for the requesting user. Pass "
            "`date_from` / `date_to` (absolute like `2026-04-23` or relative like `-7d`) to bound "
            "the window — defaults to the last 30 days, max 90 days. The `product=<ai_product>` "
            "query param is required and scopes the tool / model / day / trace breakdowns to a single "
            f"product; supported values: {', '.join(sorted(SUPPORTED_PRODUCTS))}. `by_product` is "
            "always returned for cross-product visibility. `by_day` returns a day-ascending spend "
            "series for the scoped product. Pass `hourly=true` (windows of "
            f"{BY_HOUR_MAX_WINDOW_DAYS} days or less) to additionally get `by_hour`, an hour-ascending "
            "series with per-hour cost split into uncached input / output / cache read / cache creation "
            "components. Use `refresh=true` to bypass the 5-minute response cache."
        ),
        tags=["AI observability"],
    )
    def list(self, request: Request) -> Response:
        email = self._require_email(request)

        params = _SpendQueryParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        response_data = _compute_spend_analysis(email=email, **params.validated_data)
        return Response(response_data, status=status.HTTP_200_OK)


_EU_REDIRECT_TARGET = "https://us.posthog.com/api/llm_analytics/@me/spend/"
_EU_REDIRECT_FORWARDED_PARAMS = frozenset({"date_from", "date_to", "product", "limit", "refresh", "hourly"})


def personal_spend_eu_redirect(request: HttpRequest) -> HttpResponseRedirect:
    """Redirect EU callers to the US-hosted endpoint where the data actually lives.

    EU PostHog Cloud forwards its product LLM telemetry to PostHog Cloud US, so the
    spend analysis only runs there. Returning a 302 makes the new home discoverable
    instead of serving a silent 404. Callers still need a US-valid auth token.

    Now only the fallback path of `PersonalSpendEUProxyViewSet`, used while
    `PERSONAL_SPEND_CROSS_REGION_SECRET` is not provisioned.

    The target host is hardcoded — only an allowlist of known params is forwarded
    (re-encoded via `urlencode`) so a malicious caller cannot smuggle extra path or
    fragment characters into the redirect target.
    """
    safe_params = {k: v for k, v in request.GET.items() if k in _EU_REDIRECT_FORWARDED_PARAMS}
    target = _EU_REDIRECT_TARGET
    if safe_params:
        target = f"{target}?{urlencode(safe_params)}"
    return HttpResponseRedirect(target)


# EU → US cross-region proxy: spend data only lives on US Cloud and EU
# credentials are not valid there, so the EU deployment authenticates the
# caller itself and asserts the verified email to a US-side internal endpoint
# over an HMAC-signed server-to-server call (same pattern as the Slack app's
# cross-region probe in products/slack_app/backend/api.py).

CROSS_REGION_SIGNATURE_HEADER = "X-PostHog-Spend-Signature"
CROSS_REGION_TIMESTAMP_HEADER = "X-PostHog-Spend-Timestamp"
# Fast connect failure; cold spend runs take a few seconds of ClickHouse time.
CROSS_REGION_TIMEOUT_SECONDS = (3, 15)
_CROSS_REGION_INTERNAL_PATH = "/api/llm_analytics/internal/spend/"


def _cross_region_target_url() -> str:
    # Under DEBUG a single instance plays both regions (Slack proxy's dev topology).
    if settings.DEBUG:
        return f"{settings.SITE_URL}{_CROSS_REGION_INTERNAL_PATH}"
    return f"https://us.posthog.com{_CROSS_REGION_INTERNAL_PATH}"


def sign_cross_region_spend_request(body: bytes, secret: str, *, timestamp: int | None = None) -> tuple[str, str]:
    """HMAC-SHA256 hexdigest over `v0:{ts}:{body}`; the sending half of
    `PersonalSpendCrossRegionAuthentication`. Returns (signature, timestamp)."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    hmac_input = f"v0:{ts}:{body.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), hmac_input.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()
    return digest, ts


class PersonalSpendCrossRegionAuthentication(WebhookSignatureAuthentication):
    """HMAC verification for the EU→US personal-spend proxy. The base class
    fails closed on missing headers, unset secret, stale timestamp, or digest
    mismatch; the asserted identity lives in the signed body, not `request.user`."""

    def get_signature_header(self) -> str:
        return CROSS_REGION_SIGNATURE_HEADER

    def get_timestamp_header(self) -> str:
        return CROSS_REGION_TIMESTAMP_HEADER

    def build_hmac_input(self, timestamp: str, body: str) -> str:
        return f"v0:{timestamp}:{body}"

    def get_signing_secret(self, request: Request) -> str | None:
        return settings.PERSONAL_SPEND_CROSS_REGION_SECRET or None

    def authenticate(self, request: Request) -> tuple[AnonymousUser, Any] | None:
        try:
            return super().authenticate(request)
        except UnicodeDecodeError:
            # The base class decodes the raw body before verifying; garbage
            # bytes must be an auth failure, not a 500.
            raise exceptions.AuthenticationFailed("Invalid request body encoding.")


class _InternalSpendRequestSerializer(_SpendQueryParamsSerializer):
    """The EU proxy's payload: the standard query params plus the EU-verified email."""

    email = serializers.EmailField(required=True, allow_blank=False)


class PersonalSpendInternalViewSet(viewsets.ViewSet):
    """US-side receiver for the EU personal-spend proxy (US + dev/test only).
    The asserted `email` is trusted because the body is HMAC-signed with the
    region-shared secret; the EU side authenticates and throttles the user
    before the hop, so no throttles here."""

    authentication_classes = [PersonalSpendCrossRegionAuthentication]
    permission_classes = []
    throttle_classes = []

    @extend_schema(exclude=True)
    def create(self, request: Request) -> Response:
        params = _InternalSpendRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)

        return Response(_compute_spend_analysis(**params.validated_data), status=status.HTTP_200_OK)


class _CrossRegionUpstreamError(exceptions.APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Spend analysis is temporarily unavailable."
    default_code = "cross_region_upstream_unavailable"


class PersonalSpendEUProxyViewSet(_PersonalSpendUserViewSet):
    """EU `/api/llm_analytics/@me/spend/`: authenticates locally, fetches from
    US server-side. Falls back to the 302 redirect while the secret is unset."""

    @extend_schema(
        operation_id="llm_analytics_personal_spend_eu_list",
        parameters=[_SpendQueryParamsSerializer],
        responses={200: PersonalSpendAnalysisResponseSerializer},
        description="EU mirror of the personal spend endpoint — proxies to PostHog Cloud US, where the data lives.",
        tags=["AI observability"],
    )
    def list(self, request: Request) -> HttpResponseBase:
        secret = settings.PERSONAL_SPEND_CROSS_REGION_SECRET
        if not secret:
            return personal_spend_eu_redirect(request._request)

        email = self._require_email(request)

        # Validate in-region so bad requests 400 without paying for the hop.
        params = _SpendQueryParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        # Same cache as the US compute path, so repeat loads skip the cross-region hop.
        cache_key = _cache_key(
            email, data["date_from"], data["date_to"], data["product"], data["limit"], data["hourly"]
        )
        if not data["refresh"]:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached, status=status.HTTP_200_OK)

        body = json.dumps({**data, "email": email}).encode("utf-8")
        signature, ts = sign_cross_region_spend_request(body, secret)
        try:
            upstream = requests.post(
                _cross_region_target_url(),
                data=body,
                headers={
                    "Content-Type": "application/json",
                    CROSS_REGION_SIGNATURE_HEADER: signature,
                    CROSS_REGION_TIMESTAMP_HEADER: ts,
                },
                timeout=CROSS_REGION_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.exception("personal_spend.cross_region_proxy_failed", error=str(exc))
            raise _CrossRegionUpstreamError()

        if upstream.status_code == status.HTTP_200_OK:
            try:
                payload = upstream.json()
            except ValueError:
                logger.exception("personal_spend.cross_region_proxy_bad_json")
                raise _CrossRegionUpstreamError()
            cache.set(cache_key, payload, timeout=CACHE_TIMEOUT_SECONDS)
            return Response(payload, status=status.HTTP_200_OK)

        # Relay caller-attributable upstream errors; anything else (including a
        # 401 secret mismatch between regions) is a 502.
        if upstream.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_429_TOO_MANY_REQUESTS):
            try:
                detail = upstream.json()
            except ValueError:
                detail = {"detail": f"Upstream error {upstream.status_code}"}
            return Response(detail, status=upstream.status_code)

        logger.error("personal_spend.cross_region_proxy_non_success", status_code=upstream.status_code)
        raise _CrossRegionUpstreamError()
