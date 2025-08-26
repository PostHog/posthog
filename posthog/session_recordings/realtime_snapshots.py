import json
from time import sleep
from typing import Optional

import structlog
from prometheus_client import Counter, Histogram

from posthog import settings
from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

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

REALTIME_SUBSCRIPTIONS_DATA_LENGTH = Histogram(
    "realtime_snapshots_data_length",
    "The length of the data received from the realtime channel. It's ok for this to be zero _some times_ an increase in the rate of zero indicates a possible issue.",
    labelnames=["attempt_count"],
    buckets=(0, 1, 2, 5, 10, 20, 100, 1000, float("inf")),
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
            additional_properties={
                "team_id": team_id,
                "session_id": session_id,
                "operation": "publish_realtime_subscription",
            },
        )
        raise


def get_realtime_snapshots(team_id: str, session_id: str, attempt_count=0) -> Optional[list[str]]:
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
                # s[0] is the content
                # s[1] is the time the content was written to redis
                for line in s[0].splitlines():
                    snapshots.append(line.decode("utf8"))

            REALTIME_SUBSCRIPTIONS_LOADED_COUNTER.labels(attempt_count=attempt_count).inc()
            REALTIME_SUBSCRIPTIONS_DATA_LENGTH.labels(attempt_count=attempt_count).observe(len(snapshots))
            return snapshots

        return None
    except Exception as e:
        # very broad capture to see if there are any unexpected errors
        capture_exception(
            e,
            additional_properties={
                "attempt_count": attempt_count,
                "operation": "get_realtime_snapshots",
                "team_id": team_id,
                "session_id": session_id,
            },
        )
        raise
