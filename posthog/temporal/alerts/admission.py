import time

from django.conf import settings

import structlog

from posthog import redis
from posthog.temporal.alerts.retry_policy import alert_timeouts

logger = structlog.get_logger(__name__)

# Admitted alert ids scored by lease expiry; a check joins when started, not when its query runs.
INFLIGHT_KEY = "alerts:evaluations:inflight"

# A check cannot outlive its workflow's execution timeout, so a lease this long can never lapse
# while the check it belongs to may still reach ClickHouse. A running evaluation re-holds its slot
# under the much shorter evaluation_slot_lease, so a worker that dies frees it soon after.
SLOT_LEASE_SECONDS = int(alert_timeouts(None).workflow_execution.total_seconds())

_BOOKKEEPING_ATTEMPTS = 3
_BOOKKEEPING_RETRY_SECONDS = 0.2

# One step, so overlapping scheduler runs cannot both fill the same room. Only ids absent from the
# set are added, under the expiry the scheduler chose, and only candidates carrying that expiry are
# returned: a retried admission whose first reply was lost gets the same ids back, and a member
# another run or a running check wrote is neither started nor touched by this one.
_ADMIT_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local expires_at = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
local free = limit - redis.call('ZCARD', key)
local admitted = {}
for i = 4, #ARGV do
    local alert_id = ARGV[i]
    local current = redis.call('ZSCORE', key, alert_id)
    if current then
        if tonumber(current) == expires_at then
            admitted[#admitted + 1] = alert_id
        end
    elseif free > 0 then
        redis.call('ZADD', key, ARGV[3], alert_id)
        admitted[#admitted + 1] = alert_id
        free = free - 1
    end
end
return admitted
"""

# Temporal can retry an activity while the timed-out attempt is still running, and the scheduler can
# re-admit an id whose check already holds the slot, so only the writer whose expiry is still on the
# member may remove it.
_RELEASE_OWNED_SCRIPT = """
local key = KEYS[1]
local held_until = tonumber(ARGV[1])
local removed = 0
for i = 2, #ARGV do
    local current = redis.call('ZSCORE', key, ARGV[i])
    if current and tonumber(current) == held_until then
        removed = removed + redis.call('ZREM', key, ARGV[i])
    end
end
return removed
"""

_REFRESH_OWNED_SCRIPT = """
local key = KEYS[1]
local alert_id = ARGV[1]
local held_until = tonumber(ARGV[2])
local current = redis.call('ZSCORE', key, alert_id)
if current and tonumber(current) == held_until then
    redis.call('ZADD', key, ARGV[3], alert_id)
    return 1
end
return 0
"""

# A check normally holds by rewriting the expiry the scheduler or an earlier attempt wrote, which
# changes nothing about the count. An id that has lapsed from the set (a Redis outage outlasted its
# lease, or a failover lost the set) is no longer admitted, so it only gets a slot back while there
# is room, or the checks that took the room would run over the limit alongside it.
_HOLD_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local alert_id = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZSCORE', key, alert_id) or redis.call('ZCARD', key) < limit then
    redis.call('ZADD', key, ARGV[3], alert_id)
    return 1
end
return 0
"""


def max_inflight_evaluations() -> int:
    return settings.ALERTS_MAX_INFLIGHT_EVALUATIONS


def _decode(member: bytes | str) -> str:
    return member.decode() if isinstance(member, bytes) else member


def admit_evaluation_slots(alert_ids: list[str], *, limit: int, expires_at: float) -> list[str]:
    """Admit candidates in order while the set has room and return the ids held under expires_at."""
    admitted = redis.get_client().eval(_ADMIT_SCRIPT, 1, INFLIGHT_KEY, time.time(), limit, expires_at, *alert_ids)
    return [_decode(member) for member in admitted]


def hold_evaluation_slot(alert_id: str, *, limit: int, lease_seconds: float = SLOT_LEASE_SECONDS) -> float | None:
    """Take the slot for a check that is about to run and return the expiry that identifies this holder.

    Returns None when the check no longer holds a slot and the set is full.
    """
    expires_at = time.time() + lease_seconds
    held = redis.get_client().eval(_HOLD_SCRIPT, 1, INFLIGHT_KEY, time.time(), limit, expires_at, alert_id)
    return expires_at if held else None


def refresh_evaluation_slot(alert_id: str, *, held_until: float, expires_at: float) -> bool:
    """Move the holder's expiry to expires_at and report whether the holder still owned the slot."""
    owned = redis.get_client().eval(_REFRESH_OWNED_SCRIPT, 1, INFLIGHT_KEY, alert_id, held_until, expires_at)
    return bool(owned)


def release_evaluation_slots(alert_ids: list[str], *, held_until: float) -> None:
    """Free the slots that still carry the expiry their writer was given."""
    if alert_ids:
        redis.get_client().eval(_RELEASE_OWNED_SCRIPT, 1, INFLIGHT_KEY, held_until, *alert_ids)


def release_evaluation_slot(alert_id: str, *, held_until: float) -> None:
    """Free a slot, but only if the holder identified by held_until still owns it.

    Best effort: the check this belongs to already ran, so a failure is logged rather than raised.
    """
    for attempt in range(_BOOKKEEPING_ATTEMPTS):
        try:
            release_evaluation_slots([alert_id], held_until=held_until)
            return
        except Exception:
            if attempt == _BOOKKEEPING_ATTEMPTS - 1:
                logger.exception("alerts.admission.release_failed", alert_id=alert_id)
                return
            time.sleep(_BOOKKEEPING_RETRY_SECONDS)


def inflight_alert_ids() -> set[str]:
    client = redis.get_client()
    client.zremrangebyscore(INFLIGHT_KEY, "-inf", time.time())
    return {_decode(member) for member in client.zrange(INFLIGHT_KEY, 0, -1)}
