import json
from time import sleep
from typing import Dict, List, Optional
import requests

import structlog
from prometheus_client import Counter

from posthog import settings
from posthog.redis import get_client
from posthog.settings import RECORDINGS_INGESTER_URL
from sentry_sdk import capture_exception

logger = structlog.get_logger(__name__)

PUBLISHED_REALTIME_SUBSCRIPTIONS_COUNTER = Counter(
    "realtime_snapshots_published_subscription_counter",
    "When the API is serving snapshot requests and wants to receive snapshots via a redis subscription.",
    labelnames=["attempt_count"],
)

REALTIME_SUBSCRIPTIONS_LOADED_COUNTER = Counter(
    "realtime_snapshots_loaded_counter",
    "When the API is serving snapshot requests successfully loads snapshots from realtime channel.",
    labelnames=["attempt_count"],
)


SUBSCRIPTION_CHANNEL = "@posthog/replay/realtime-subscriptions"


def get_key(team_id: str, suffix: str) -> str:
    return f"@posthog/replay/snapshots/team-{team_id}/{suffix}"


def publish_subscription(team_id: str, session_id: str) -> None:
    """
    Publishing a subscription notifies each instance of Mr Blobby of the request for realtime playback
    Only zero or one instances will be handling the session, if they are, they will start publishing
    the snapshot data to Redis so that it can be played before the data has been sent to blob storage
    """
    try:
        redis = get_client(settings.SESSION_RECORDING_REDIS_URL)
        redis.publish(
            SUBSCRIPTION_CHANNEL,
            json.dumps({"team_id": team_id, "session_id": session_id}),
        )
    except Exception as e:
        capture_exception(
            e,
            extras={
                "operation": "publish_realtime_subscription",
            },
            tags={"team_id": team_id, "session_id": session_id},
        )
        raise e


def get_realtime_snapshots(team_id: str, session_id: str, attempt_count=0) -> Optional[List[Dict]]:
    try:
        redis = get_client(settings.SESSION_RECORDING_REDIS_URL)
        key = get_key(team_id, session_id)
        encoded_snapshots = redis.zrange(key, 0, -1, withscores=True)

        # We always publish as it could be that a rebalance has occurred
        # and the consumer doesn't know it should be sending data to redis
        publish_subscription(team_id, session_id)

        if not encoded_snapshots and attempt_count < settings.REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_MAX:
            logger.info(
                "No realtime snapshots found, publishing subscription and retrying",
                team_id=team_id,
                session_id=session_id,
                attempt_count=attempt_count,
            )

            PUBLISHED_REALTIME_SUBSCRIPTIONS_COUNTER.labels(attempt_count=attempt_count).inc()

            sleep(
                settings.REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS
                if attempt_count < 4
                else settings.REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS * 2
            )
            return get_realtime_snapshots(team_id, session_id, attempt_count + 1)

        if encoded_snapshots:
            snapshots = []

            for s in encoded_snapshots:
                for line in s[0].splitlines():
                    snapshots.append(json.loads(line))

            REALTIME_SUBSCRIPTIONS_LOADED_COUNTER.labels(attempt_count=attempt_count).inc()
            return snapshots

        return None
    except Exception as e:
        # very broad capture to see if there are any unexpected errors
        capture_exception(
            e,
            extras={
                "attempt_count": attempt_count,
                "operation": "get_realtime_snapshots",
            },
            tags={"team_id": team_id, "session_id": session_id},
        )
        raise e
