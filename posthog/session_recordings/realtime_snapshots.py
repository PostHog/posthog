import json
from time import sleep
from typing import Dict, List, Optional

import structlog
from posthog.redis import get_client

logger = structlog.get_logger(__name__)


SUBSCRIPTION_CHANNEL = "@posthog/replay/realtime-subscriptions"
ATTEMPT_MAX = 10
ATTEMPT_TIMEOUT_SECONDS = 5


def get_key(team_id: str, suffix: str) -> str:
    return f"@posthog/replay/snapshots/team-{team_id}/{suffix}"


# TODO: Type this better
def get_realtime_snapshots(team_id: str, session_id: str, attempt_count=0) -> Optional[List[Dict]]:
    redis = get_client()
    key = get_key(team_id, session_id)
    encoded_snapshots = redis.zrange(key, 0, -1, withscores=True)

    if not encoded_snapshots and attempt_count < ATTEMPT_MAX:
        logger.info(
            "No realtime snapshots found, publishing subscription and retrying",
            team_id=team_id,
            session_id=session_id,
            attempt_count=attempt_count,
        )
        # If we don't have it we could be in the process of getting it and syncing it
        redis.publish(SUBSCRIPTION_CHANNEL, json.dumps({"team_id": team_id, "session_id": session_id}))
        sleep(ATTEMPT_TIMEOUT_SECONDS / ATTEMPT_MAX)
        return get_realtime_snapshots(team_id, session_id, attempt_count + 1)

    if encoded_snapshots:
        snapshots = []

        for s in encoded_snapshots:
            for line in s[0].splitlines():
                snapshots.append(json.loads(line))

        return snapshots

    return None
