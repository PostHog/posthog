import json
import time

import structlog
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.redis import get_client

from products.customer_analytics.backend.facade.contracts import AccountPresenceViewer

ACCOUNT_PRESENCE_TTL_SECONDS = 30

logger = structlog.get_logger(__name__)


@frozen
class _AccountPresenceKeys:
    roster: str
    profiles: str


def _presence_keys(team_id: int, account_id: str) -> _AccountPresenceKeys:
    prefix = f"customer_analytics:account_presence:{team_id}:{account_id}"
    return _AccountPresenceKeys(roster=f"{prefix}:viewers", profiles=f"{prefix}:profiles")


def heartbeat_account_presence(
    *, team_id: int, account_id: str, viewer: AccountPresenceViewer
) -> list[AccountPresenceViewer]:
    keys = _presence_keys(team_id, account_id)
    now = time.time()
    expires_at = now + ACCOUNT_PRESENCE_TTL_SECONDS

    try:
        redis_client = get_client()
        pipeline = redis_client.pipeline()
        pipeline.zadd(keys.roster, {str(viewer.user_id): expires_at})
        pipeline.hset(keys.profiles, str(viewer.user_id), json.dumps({"display_name": viewer.display_name}))
        pipeline.expire(keys.roster, ACCOUNT_PRESENCE_TTL_SECONDS)
        pipeline.expire(keys.profiles, ACCOUNT_PRESENCE_TTL_SECONDS)
        pipeline.zremrangebyscore(keys.roster, "-inf", now)
        pipeline.zrangebyscore(keys.roster, now, "+inf")
        active_user_ids = pipeline.execute()[-1]
        profiles = redis_client.hmget(keys.profiles, active_user_ids)
    except RedisError:
        logger.warning("customer_analytics_account_presence_redis_error", exc_info=True)
        return []

    peers: list[AccountPresenceViewer] = []
    for raw_user_id, raw_profile in zip(active_user_ids, profiles):
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue
        if user_id == viewer.user_id or raw_profile is None:
            continue
        try:
            profile = json.loads(raw_profile)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        display_name = profile.get("display_name") if isinstance(profile, dict) else None
        if isinstance(display_name, str):
            peers.append(AccountPresenceViewer(user_id=user_id, display_name=display_name))
    return sorted(peers, key=lambda peer: (peer.display_name.casefold(), peer.user_id))
