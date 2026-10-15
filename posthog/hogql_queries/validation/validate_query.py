"""Run a query's own validation rules against it without executing it.

`QueryRunner.validate()` runs the rules in this package from `calculate()`, so a stored query is
only judged while it is read, and only on a read that misses the result cache. A caller that has
to know whether a stored query can run at all, such as an insight write or an alert check, asks
here instead of waiting for the next uncached read to tell it.
"""

import logging
from typing import Any

from pydantic import BaseModel
from rest_framework.exceptions import ErrorDetail, ValidationError

from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner_or_none
from posthog.models import Team, User

logger = logging.getLogger(__name__)


@frozen
class QueryRuleViolation:
    code: str
    message: str
    query_kind: str


def first_query_rule_violation(
    query: dict[str, Any] | BaseModel,
    *,
    team: Team,
    user: User | None = None,
) -> QueryRuleViolation | None:
    """The first validation rule the query breaks, or None when every rule passes."""
    runner = _runner_or_none(query, team=team, user=user)
    if runner is None:
        return None

    try:
        runner.validate()
    except ValidationError as error:
        detail = _first_detail(error)
        code = detail.code if isinstance(detail, ErrorDetail) else None
        return QueryRuleViolation(
            code=code or "invalid",
            message=str(detail),
            query_kind=str(getattr(runner.query, "kind", "unknown")),
        )
    except Exception:
        # Only a rule saying "this query can never run" is a verdict on the query. Anything else a
        # rule throws is our bug, and acting on it would reject a query the read path accepts.
        logger.exception("Query validation rule failed")
        return None

    return None


def rule_violation_message(error: ValidationError) -> str:
    """The sentence a validation rule raised, out of DRF's list-or-dict-of-lists detail."""
    return str(_first_detail(error))


def _runner_or_none(query: dict[str, Any] | BaseModel, *, team: Team, user: User | None) -> QueryRunner | None:
    try:
        return get_query_runner_or_none(query, team, user=user)
    except Exception:
        # A payload no runner can be built for is one the read path already handles its own way.
        # Refusing it here would turn every shape we do not recognize into a rejection.
        return None


def _first_detail(error: ValidationError) -> ErrorDetail | str:
    # DRF coerces detail to a list, or to a dict of lists when the rule named a field.
    detail: ErrorDetail | list | dict | str = error.detail
    if isinstance(detail, dict):
        detail = next(iter(detail.values()), "")
    if isinstance(detail, list):
        detail = detail[0] if detail else ""
    return detail if isinstance(detail, ErrorDetail | str) else str(detail)
