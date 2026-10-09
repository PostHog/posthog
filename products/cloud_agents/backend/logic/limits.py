"""Per-project limits on runs: how many run at once, and how fast new runs start."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from django.db import connection

import structlog
from prometheus_client import Counter

from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume, refund

from ..facade.contracts import ConcurrencyLimited, CreateRateLimited
from ..models import TeamCloudAgentsConfig

logger = structlog.get_logger(__name__)

DEFAULT_MAX_CONCURRENT_RUNS: Final = 5
DEFAULT_CREATE_RATE_PER_HOUR: Final = 60
CREATE_RATE_BURST: Final = 10
CREATE_RATE_KEY_PREFIX: Final = "cloud_agents_create_rate:"

CREATE_RATE_UNAVAILABLE_COUNTER = Counter(
    "cloud_agents_create_rate_unavailable_total",
    "Run create rate checks that Redis could not answer and that were allowed.",
)


def max_concurrent_runs(team_id: int) -> int:
    override = TeamCloudAgentsConfig.objects.for_team(team_id).values_list("max_concurrent_runs", flat=True).first()
    return override if override is not None else DEFAULT_MAX_CONCURRENT_RUNS


def create_rate_per_hour(team_id: int) -> int:
    override = TeamCloudAgentsConfig.objects.for_team(team_id).values_list("create_rate_per_hour", flat=True).first()
    return override if override else DEFAULT_CREATE_RATE_PER_HOUR


def concurrency_guard(team_id: int, count_active: Callable[[], int]) -> None:
    """Raise `ConcurrencyLimited` when the project is at its limit of active runs.

    Call this inside `transaction.atomic()`, and create the run in the same transaction. The
    advisory lock makes two concurrent creates count one after the other, and it ends with the
    transaction. The Team row is not locked, because foreign-key checks of unrelated writes wait on it.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("concurrency_guard must be called inside transaction.atomic()")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"cloud-agents-concurrency:{team_id}"])
    limit = max_concurrent_runs(team_id)
    active = count_active()
    if active >= limit:
        raise ConcurrencyLimited(limit=limit, active=active)


def _create_rate_key(team_id: int) -> str:
    return f"{CREATE_RATE_KEY_PREFIX}{team_id}"


def _create_rate_budget(team_id: int) -> Budget:
    per_hour = create_rate_per_hour(team_id)
    return Budget(burst=min(CREATE_RATE_BURST, per_hour), per_hour=per_hour)


def consume_create_rate(team_id: int) -> None:
    """Take one token for a new run. Raise `CreateRateLimited` when the project has none."""
    decision = consume(_create_rate_key(team_id), _create_rate_budget(team_id))
    match decision:
        case BucketUnavailable():
            # Fail open: a Redis outage must not stop all new runs. The concurrency limit still applies.
            CREATE_RATE_UNAVAILABLE_COUNTER.inc()
            logger.warning("cloud_agents_create_rate_unavailable", team_id=team_id)
        case BucketDecision(allowed=False):
            raise CreateRateLimited(retry_after=max(decision.retry_after, 1))


def refund_create_rate(team_id: int) -> None:
    """Give back the token of a create that did no work, for example one that failed validation."""
    refund(_create_rate_key(team_id), _create_rate_budget(team_id))
