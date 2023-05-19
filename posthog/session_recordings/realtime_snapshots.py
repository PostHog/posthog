import json
from typing import Dict, List, Optional
from posthog.redis import get_client


def get_key(team_id: str, suffix: str) -> str:
    return f"@posthog/replay/snapshots/team-{team_id}/{suffix}"


# TODO: Type this better
def get_realtime_snapshots(team_id: str, session_id: str) -> Optional[List[Dict]]:
    redis = get_client()
    snapshots = redis.zrange(get_key(team_id, f"session-{session_id}"), 0, -1, withscores=True)

    if snapshots:
        return [json.loads(s[0]) for s in snapshots]

    return None
