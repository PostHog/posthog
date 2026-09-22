import time
from collections.abc import Callable

from django.conf import settings

import structlog

from posthog import redis
from posthog.temporal.alerts.retry_policy import alert_timeouts

logger = structlog.get_logger(__name__)

# Admitted alert ids scored by lease expiry; a check joins when started, not when its query runs.
INFLIGHT_KEY = "alerts:evaluations:inflight"

# A check cannot outlive its workflow's execution timeout, so a lease this long can never lapse
# while the check it belongs to may still reach ClickHouse.
SLOT_LEASE_SECONDS = int(alert_timeouts(None).workflow_execution.total_seconds())

_UNLIMITED = 2**31
_BOOKKEEPING_ATTEMPTS = 3
_BOOKKEEPING_RETRY_SECONDS = 0.2

# One step, so overlapping scheduler runs cannot both fill the same room; an existing member keeps
# the later expiry, so re-admitting an id never shortens the lease its running check holds.
_ADMIT_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local expires_at = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
local free = limit - redis.call('ZCARD', key)
local admitted = {}
for i = 4, #ARGV do
    if #admitted >= free then
        break
    end
    local alert_id = ARGV[i]
    local current = redis.call('ZSCORE', key, alert_id)
    if not current or tonumber(current) < expires_at then
        redis.call('ZADD', key, expires_at, alert_id)
    end
    admitted[#admitted + 1] = alert_id
end
return admitted
"""


def max_inflight_evaluations() -> int:
    return settings.ALERTS_MAX_INFLIGHT_EVALUATIONS


def admit_evaluation_slots(alert_ids: list[str], *, limit: int) -> list[str]:
    """Admit candidates in order while the set has room and return the ids that got a slot."""
    if not alert_ids:
        return []
    now = time.time()
    admitted = redis.get_client().eval(_ADMIT_SCRIPT, 1, INFLIGHT_KEY, now, limit, now + SLOT_LEASE_SECONDS, *alert_ids)
    return [member.decode() if isinstance(member, bytes) else member for member in admitted]


def reserve_evaluation_slots(alert_ids: list[str]) -> None:
    admit_evaluation_slots(alert_ids, limit=_UNLIMITED)


def _best_effort(operation: Callable[[], object], event: str, alert_id: str) -> None:
    # Bookkeeping must not fail a check that already ran, so retry briefly and then log instead of raising.
    for attempt in range(_BOOKKEEPING_ATTEMPTS):
        try:
            operation()
            return
        except Exception:
            if attempt == _BOOKKEEPING_ATTEMPTS - 1:
                logger.exception(event, alert_id=alert_id)
                return
            time.sleep(_BOOKKEEPING_RETRY_SECONDS)


def hold_evaluation_slot(alert_id: str) -> None:
    _best_effort(lambda: reserve_evaluation_slots([alert_id]), "alerts.admission.hold_failed", alert_id)


def release_evaluation_slot(alert_id: str) -> None:
    _best_effort(lambda: redis.get_client().zrem(INFLIGHT_KEY, alert_id), "alerts.admission.release_failed", alert_id)


def inflight_alert_ids() -> set[str]:
    client = redis.get_client()
    client.zremrangebyscore(INFLIGHT_KEY, "-inf", time.time())
    return {member.decode() if isinstance(member, bytes) else member for member in client.zrange(INFLIGHT_KEY, 0, -1)}


def count_inflight_evaluations() -> int:
    client = redis.get_client()
    client.zremrangebyscore(INFLIGHT_KEY, "-inf", time.time())
    return int(client.zcard(INFLIGHT_KEY))
