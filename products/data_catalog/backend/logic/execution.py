"""Metric execution — run a metric's definition through the standard HogQL query runner.

The definition is executed verbatim (same engine as insights and the SQL editor, so results are
identical), wrapped in a normalized envelope with a deep link the MCP layer surfaces. Date params map
into the query's dateRange for insight/node kinds and are rejected on HogQLQuery kinds, whose window
is fixed in the SQL.
"""

import json
from copy import deepcopy
from datetime import timedelta
from typing import Optional
from urllib.parse import quote

from django.utils import timezone

from pydantic import BaseModel
from rest_framework.exceptions import ValidationError

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.services.query import process_query_dict
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh
from posthog.models import Team, User
from posthog.utils import absolute_uri

from ..facade.enums import MARKDOWN_DEFINITION_KIND
from ..models import Metric
from .exceptions import MetricHasNoDefinition

_LAST_RUN_THROTTLE = timedelta(minutes=30)


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

    if metric.definition_kind == MARKDOWN_DEFINITION_KIND:
        # Agent-calculated: return the steps to follow instead of executing a query. Still recorded
        # as a run for attribution.
        _touch_last_run(team, metric)
        _capture_run(user, team, metric)
        return _markdown_envelope(metric)

    query = deepcopy(metric.definition)
    _apply_date_params(query, date_from, date_to, interval)

    execution_mode = (
        execution_mode_from_refresh(refresh) if refresh else ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    )
    try:
        with tags_context(product=Product.DATA_CATALOG, feature=Feature.QUERY):
            raw = process_query_dict(team, query, execution_mode=execution_mode, user=user, query_id=query_id)
    except ExposedHogQLError as e:
        raise ValidationError(
            {
                "field": "definition",
                "error": f"This metric could not run: {e}",
                "hint": "A table or column it references may no longer exist. Check system.information_schema.tables.",
            }
        )
    except Exception as e:
        capture_exception(e)
        raise ValidationError(
            {
                "field": "definition",
                "error": "This metric failed to run.",
                "hint": "Check the definition and try again.",
            }
        )

    payload = raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
    _touch_last_run(team, metric)
    _capture_run(user, team, metric)
    return _envelope(metric, payload, team)


def _apply_date_params(query: dict, date_from: Optional[str], date_to: Optional[str], interval: Optional[str]) -> None:
    if date_from is None and date_to is None and interval is None:
        return
    if query.get("kind") == "HogQLQuery":
        raise ValidationError(
            {
                "field": "date_from",
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


def _envelope(metric: Metric, payload: object, team: Team) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    return {
        "status": metric.status,
        "unit": metric.unit or None,
        "kind": metric.definition_kind,
        "results": payload.get("results"),
        "compiled_query": payload.get("hogql"),
        "query_status": payload.get("query_status"),
        "posthog_url": _deep_link(metric, team),
        "instructions": None,
    }


def _markdown_envelope(metric: Metric) -> dict:
    return {
        "status": metric.status,
        "unit": metric.unit or None,
        "kind": metric.definition_kind,
        "results": None,
        "compiled_query": None,
        "query_status": None,
        "posthog_url": None,
        "instructions": (metric.definition or {}).get("markdown"),
    }


def _deep_link(metric: Metric, team: Team) -> str:
    definition = metric.definition or {}
    if definition.get("kind") == "HogQLQuery":
        path = f"/project/{team.id}/sql?open_query={quote(definition.get('query', ''))}"
    else:
        path = f"/project/{team.id}/insights/new#q={quote(json.dumps(definition))}"
    return absolute_uri(path)


def _touch_last_run(team: Team, metric: Metric) -> None:
    now = timezone.now()
    if metric.last_run_at is None or (now - metric.last_run_at) > _LAST_RUN_THROTTLE:
        # Bypass save() (and the activity mixin) — a run is not an audit-worthy change.
        Metric.objects.for_team(team.id).filter(pk=metric.pk).update(last_run_at=now)
        metric.last_run_at = now


def _capture_run(user: Optional[User], team: Team, metric: Metric) -> None:
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
        },
    )
