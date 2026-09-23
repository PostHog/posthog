import time

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

# Temporal can retry an activity while the timed-out attempt is still running, so only the attempt
# whose expiry is still on the member may remove it.
_RELEASE_OWNED_SCRIPT = """
local key = KEYS[1]
local alert_id = ARGV[1]
local held_until = tonumber(ARGV[2])
local current = redis.call('ZSCORE', key, alert_id)
if current and tonumber(current) == held_until then
    return redis.call('ZREM', key, alert_id)
end
return 0
"""


def max_inflight_evaluations() -> int:
    return settings.ALERTS_MAX_INFLIGHT_EVALUATIONS


def _admit(alert_ids: list[str], *, limit: int, now: float) -> list[str]:
    admitted = redis.get_client().eval(_ADMIT_SCRIPT, 1, INFLIGHT_KEY, now, limit, now + SLOT_LEASE_SECONDS, *alert_ids)
    return [member.decode() if isinstance(member, bytes) else member for member in admitted]


def admit_evaluation_slots(alert_ids: list[str], *, limit: int) -> list[str]:
    """Admit candidates in order while the set has room and return the ids that got a slot."""
    if not alert_ids:
        return []
    return _admit(alert_ids, limit=limit, now=time.time())


def reserve_evaluation_slots(alert_ids: list[str]) -> float:
    """Take slots regardless of the limit and return the expiry they were given."""
    now = time.time()
    if alert_ids:
        _admit(alert_ids, limit=_UNLIMITED, now=now)
    return now + SLOT_LEASE_SECONDS


def hold_evaluation_slot(alert_id: str) -> float:
    """Take the slot for an evaluation that is about to run and return the expiry that identifies this holder."""
    for attempt in range(_BOOKKEEPING_ATTEMPTS):
        try:
            return reserve_evaluation_slots([alert_id])
        except Exception:
            if attempt == _BOOKKEEPING_ATTEMPTS - 1:
                raise
            time.sleep(_BOOKKEEPING_RETRY_SECONDS)
    raise AssertionError("unreachable")


def release_evaluation_slot(alert_id: str, *, held_until: float) -> None:
    """Free a slot, but only if the holder identified by held_until still owns it.

    Best effort: the check this belongs to already ran, so a failure is logged rather than raised.
    """
    for attempt in range(_BOOKKEEPING_ATTEMPTS):
        try:
            redis.get_client().eval(_RELEASE_OWNED_SCRIPT, 1, INFLIGHT_KEY, alert_id, held_until)
            return
        except Exception:
            if attempt == _BOOKKEEPING_ATTEMPTS - 1:
                logger.exception("alerts.admission.release_failed", alert_id=alert_id)
                return
            time.sleep(_BOOKKEEPING_RETRY_SECONDS)


def release_evaluation_slots(alert_ids: list[str]) -> None:
    if alert_ids:
        redis.get_client().zrem(INFLIGHT_KEY, *alert_ids)


def inflight_alert_ids() -> set[str]:
    client = redis.get_client()
    client.zremrangebyscore(INFLIGHT_KEY, "-inf", time.time())
    return {member.decode() if isinstance(member, bytes) else member for member in client.zrange(INFLIGHT_KEY, 0, -1)}


def count_inflight_evaluations() -> int:
    client = redis.get_client()
    client.zremrangebyscore(INFLIGHT_KEY, "-inf", time.time())
    return int(client.zcard(INFLIGHT_KEY))
