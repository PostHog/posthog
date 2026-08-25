"""
Business rules for a person's gateway spend limit.

The gateway stores the limit; this product keeps no copy. This module is the only
place that knows the gateway's budget shape, so the facade's contract survives a
gateway change.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus

import structlog

from posthog.llm.gateway_internal_client import (
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    clear_user_budget,
    get_user_budget,
    set_user_budget,
)
from posthog.models.user import User

from .facade.contracts import SpendLimit

logger = structlog.get_logger(__name__)


class SpendLimitsUnsupported(Exception):
    """This deployment's gateway cannot hold a spend limit, so none can be set."""


class SpendLimitsUnavailable(Exception):
    """The gateway call failed before completing, so nothing was read or changed."""


class SpendLimitsRejected(Exception):
    """The gateway refused the request as invalid, so nothing changed."""


def read_spend_limit(team_id: int, user: User) -> SpendLimit:
    try:
        with _gateway_call("read", team_id):
            budget = get_user_budget(team_id, _spend_node(user))
    except SpendLimitsUnsupported:
        # A read can report that limits are unavailable here, where a write has to fail.
        return _unavailable()
    if budget is None:
        return _no_limit()
    return SpendLimit(limit_usd=budget.limit_usd, window_seconds=budget.window_seconds, available=True)


def write_spend_limit(team_id: int, user: User, *, limit_usd: str, window_seconds: int) -> SpendLimit:
    with _gateway_call("write", team_id):
        budget = set_user_budget(team_id, _spend_node(user), limit_usd, window_seconds)
    return SpendLimit(limit_usd=budget.limit_usd, window_seconds=budget.window_seconds, available=True)


def remove_spend_limit(team_id: int, user: User) -> SpendLimit:
    with _gateway_call("clear", team_id):
        clear_user_budget(team_id, _spend_node(user))
    return _no_limit()


def _no_limit() -> SpendLimit:
    return SpendLimit(limit_usd=None, window_seconds=None, available=True)


def _unavailable() -> SpendLimit:
    return SpendLimit(limit_usd=None, window_seconds=None, available=False)


def _spend_node(user: User) -> str:
    # The gateway meters spend per user node, so this has to be the node a cloud
    # run's token asserts. `get_actor_distinct_id` in products/tasks derives the
    # run side the same way; if the two drift, the gateway counts spend against a
    # node nothing configured and the limit silently does nothing.
    return user.distinct_id or f"user_{user.id}"


@contextmanager
def _gateway_call(operation: str, team_id: int) -> Iterator[None]:
    try:
        yield
    except AIGatewayNotConfigured as exc:
        raise SpendLimitsUnsupported from exc
    except AIGatewayInternalError as exc:
        # The client calls a per-user path; "no budget for this user" is a 2xx
        # with no row, so a 404 means this gateway serves no budgets route at all.
        if exc.status_code == HTTPStatus.NOT_FOUND:
            raise SpendLimitsUnsupported from exc
        logger.warning(
            "ai_gateway_user_spend_limit_gateway_error",
            operation=operation,
            team_id=team_id,
            status_code=exc.status_code,
            error=str(exc),
        )
        # A 4xx means the gateway understood and refused the request, which points
        # at drift between its validation and ours; anything else means the call
        # never completed cleanly.
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            raise SpendLimitsRejected from exc
        raise SpendLimitsUnavailable from exc
