"""Metric execution — run a metric's definition through the standard HogQL query runner.

The definition is executed through the same engine as insights and the SQL editor, so results are
identical. Bare series nodes (EventsNode, ActionsNode, DataWarehouseNode) aren't runnable on their
own, so they execute as a single-series trends query; the envelope keeps the stored kind. Date
params map into the prepared query's dateRange for insight/node kinds and are rejected on HogQLQuery
kinds, whose window is fixed in the SQL. The deep link encodes the prepared query — overrides
included — so opening it reproduces exactly what ran.
"""

import json
from copy import deepcopy
from datetime import timedelta
from typing import Optional
from urllib.parse import quote

from django.utils import timezone

from pydantic import BaseModel
from rest_framework.exceptions import Throttled, ValidationError

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import (
    Feature,
    Product,
    get_query_tag_value,
    is_api_key_access_method,
    tags_context,
)
from posthog.errors import ExposedCHQueryError
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh
from posthog.models import Team, User
from posthog.utils import absolute_uri

from ..facade.enums import HOGQL_DEFINITION_KIND, MARKDOWN_DEFINITION_KIND, NODE_DEFINITION_KINDS
from ..models import Metric
from .drift import compute_drift
from .exceptions import MetricHasNoDefinition

_LAST_RUN_THROTTLE = timedelta(minutes=30)

# Same wording as /query/'s concurrency response, so agents see one message for one condition.
_CONCURRENCY_LIMIT_MESSAGE = "Too many queries are running right now — please try again in a moment."


def run_metric(
    *,
    team: Team,
    metric: Metric,
    user: Optional[User],
    refresh: bool | str | None = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: Optional[str] = None,
    query_id: Optional[str] = None,
) -> dict:
    if not metric.definition:
        raise MetricHasNoDefinition()

    is_drifted = compute_drift([metric])[metric.id]

    if metric.definition_kind == MARKDOWN_DEFINITION_KIND:
        # Agent-calculated: return the steps to follow instead of executing a query. Still recorded
        # as a run for attribution.
        _touch_last_run(team, metric)
        _capture_run(user, team, metric, is_drifted)
        return _markdown_envelope(metric, is_drifted)

    query = prepare_execution_query(metric.definition, date_from=date_from, date_to=date_to, interval=interval)

    execution_mode = (
        execution_mode_from_refresh(refresh) if refresh else ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    )
    try:
        with tags_context(product=Product.DATA_CATALOG, feature=Feature.QUERY):
            raw = process_query_dict(
                team,
                query,
                execution_mode=execution_mode,
                user=user,
                query_id=query_id,
                # Mirror /query and endpoint execution: API-key runs are subject to the same query
                # safeguards (rejected constructs, API-team concurrency limiter) as those paths.
                is_query_service=is_api_key_access_method(get_query_tag_value("access_method")),
            )
    except (ExposedHogQLError, ExposedCHQueryError) as e:
        raise ValidationError(
            {
                "field": "definition",
                "error": f"This metric could not run: {e}",
                "hint": "A table or column it references may no longer exist. Check system.information_schema.tables.",
            }
        )
    except ConcurrencyLimitExceeded:
        raise Throttled(detail=_CONCURRENCY_LIMIT_MESSAGE)
    except ValidationError:
        raise
    except Exception as e:
        capture_exception(e)
        raise

    payload = raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("error"):
        # The engine reports schema-validation failures as an error payload instead of raising; a
        # run that produced no results must not read as a success.
        raise ValidationError(
            {
                "field": "definition",
                "error": f"This metric could not run: {payload['error']}",
                "hint": "The definition (or a date/interval override) does not form a valid query.",
            }
        )

    _touch_last_run(team, metric)
    _capture_run(user, team, metric, is_drifted)
    return _envelope(metric, payload, team, query, is_drifted)


def prepare_execution_query(
    definition: dict,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: Optional[str] = None,
) -> dict:
    """The exact query handed to the engine: the stored definition, node kinds wrapped runnable,
    date/interval overrides applied."""
    query = deepcopy(definition)
    if query.get("kind") in NODE_DEFINITION_KINDS:
        # A bare series node has no query runner of its own; run it as a single-series trends query.
        query = {"kind": "TrendsQuery", "series": [query]}
    _apply_date_params(query, date_from, date_to, interval)
    return query


def _apply_date_params(query: dict, date_from: Optional[str], date_to: Optional[str], interval: Optional[str]) -> None:
    if date_from is None and date_to is None and interval is None:
        return
    if query.get("kind") == HOGQL_DEFINITION_KIND:
        field = "date_from" if date_from is not None else ("date_to" if date_to is not None else "interval")
        raise ValidationError(
            {
                "field": field,
                "error": "This metric's dates are fixed in its SQL and cannot be overridden at run time.",
                "hint": "Report the definition's own window, or ask for a parameterized metric.",
            }
        )
    date_range = dict(query.get("dateRange") or {})
    if date_from is not None:
        date_range["date_from"] = date_from
    if date_to is not None:
        date_range["date_to"] = date_to
    if date_range:
        query["dateRange"] = date_range
    if interval is not None:
        query["interval"] = interval


def _envelope(metric: Metric, payload: dict, team: Team, prepared_query: dict, is_drifted: bool) -> dict:
    return {
        "status": metric.status,
        "is_drifted": is_drifted,
        "unit": metric.unit or None,
        "kind": metric.definition_kind,
        "results": payload.get("results"),
        "compiled_query": payload.get("hogql"),
        "query_status": payload.get("query_status"),
        "posthog_url": _deep_link(team, prepared_query),
        "instructions": None,
    }


def _markdown_envelope(metric: Metric, is_drifted: bool) -> dict:
    return {
        "status": metric.status,
        "is_drifted": is_drifted,
        "unit": metric.unit or None,
        "kind": metric.definition_kind,
        "results": None,
        "compiled_query": None,
        "query_status": None,
        "posthog_url": None,
        "instructions": (metric.definition or {}).get("markdown"),
    }


def _deep_link(team: Team, prepared_query: dict) -> str:
    if prepared_query.get("kind") == HOGQL_DEFINITION_KIND:
        # A JSON node in open_query prefills the SQL editor with the full query, values included;
        # a bare SQL string would drop the values.
        node = {"kind": "DataVisualizationNode", "source": prepared_query}
        path = f"/project/{team.id}/sql?open_query={quote(json.dumps(node))}"
    else:
        # The insight scene expects the InsightVizNode wrapper insights themselves store in #q=.
        node = {"kind": "InsightVizNode", "source": prepared_query}
        path = f"/project/{team.id}/insights/new#q={quote(json.dumps(node))}"
    return absolute_uri(path)


def _touch_last_run(team: Team, metric: Metric) -> None:
    now = timezone.now()
    if metric.last_run_at is None or (now - metric.last_run_at) > _LAST_RUN_THROTTLE:
        # Bypass save() (and the activity mixin) — a run is not an audit-worthy change.
        Metric.objects.for_team(team.id).filter(pk=metric.pk).update(last_run_at=now)
        metric.last_run_at = now


def _capture_run(user: Optional[User], team: Team, metric: Metric, is_drifted: bool) -> None:
    if user is None:
        return
    report_user_action(
        user=user,
        event="data catalog metric run",
        team=team,
        properties={
            "metric_id": str(metric.id),
            "metric_name": metric.name,
            "definition_kind": metric.definition_kind,
            "status": metric.status,
            "is_drifted": is_drifted,
        },
    )
