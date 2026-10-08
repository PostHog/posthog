import json
import time

import structlog
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.redis import get_client

from products.customer_analytics.backend.facade.contracts import AccountPresenceViewer

ACCOUNT_PRESENCE_TTL_SECONDS = 90

logger = structlog.get_logger(__name__)


@frozen
class _AccountPresenceKeys:
    roster: str
    profile_prefix: str

    def get_profile_key(self, user_id: int) -> str:
        return f"{self.profile_prefix}:{user_id}"


def _presence_keys(team_id: int, account_id: str) -> _AccountPresenceKeys:
    prefix = f"customer_analytics:account_presence:{team_id}:{account_id}"
    return _AccountPresenceKeys(roster=f"{prefix}:viewers", profile_prefix=f"{prefix}:profiles")


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
        pipeline.set(
            keys.get_profile_key(viewer.user_id),
            json.dumps({"display_name": viewer.display_name}),
            ex=ACCOUNT_PRESENCE_TTL_SECONDS,
        )
        pipeline.expire(keys.roster, ACCOUNT_PRESENCE_TTL_SECONDS)
        pipeline.zremrangebyscore(keys.roster, "-inf", now)
        pipeline.zrangebyscore(keys.roster, now, "+inf")
        active_user_ids = pipeline.execute()[-1]
        profiles = redis_client.mget([keys.get_profile_key(int(user_id)) for user_id in active_user_ids])
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


def list_account_presence(*, team_id: int, account_ids: list[str]) -> dict[str, list[AccountPresenceViewer]]:
    if not account_ids:
        return {}

    now = time.time()
    keys_by_account_id = {account_id: _presence_keys(team_id, account_id) for account_id in account_ids}
    try:
        redis_client = get_client()
        pipeline = redis_client.pipeline()
        for keys in keys_by_account_id.values():
            pipeline.zremrangebyscore(keys.roster, "-inf", now)
            pipeline.zrangebyscore(keys.roster, now, "+inf")
        results = pipeline.execute()
        active_user_ids_by_account_id = {
            account_id: active_user_ids
            for (account_id, _), active_user_ids in zip(keys_by_account_id.items(), results[1::2])
        }
        profile_locations: list[tuple[str, int]] = []
        for account_id, active_user_ids in active_user_ids_by_account_id.items():
            for user_id in active_user_ids:
                try:
                    profile_locations.append((account_id, int(user_id)))
                except (TypeError, ValueError):
                    continue
        profiles = redis_client.mget(
            [keys_by_account_id[account_id].get_profile_key(user_id) for account_id, user_id in profile_locations]
        )
    except RedisError:
        logger.warning("customer_analytics_account_presence_redis_error", exc_info=True)
        return {}

    viewers_by_account_id: dict[str, list[AccountPresenceViewer]] = {account_id: [] for account_id in account_ids}
    for (account_id, user_id), raw_profile in zip(profile_locations, profiles):
        if raw_profile is None:
            continue
        try:
            profile = json.loads(raw_profile)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        display_name = profile.get("display_name") if isinstance(profile, dict) else None
        if isinstance(display_name, str):
            viewers_by_account_id[account_id].append(AccountPresenceViewer(user_id=user_id, display_name=display_name))

    return {
        account_id: sorted(viewers, key=lambda viewer: (viewer.display_name.casefold(), viewer.user_id))
        for account_id, viewers in viewers_by_account_id.items()
    }
