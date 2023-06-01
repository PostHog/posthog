from posthog.redis import redis, get_client
import time
import posthoganalytics
from sentry_sdk import capture_exception

REDIS_LOCK_TOKEN = "posthog:decide_analytics:lock"
CACHE_BUCKET_SIZE = 60 * 2  # duration in seconds


def get_team_request_key(team_id: int) -> str:
    return f"posthog:decide_requests:{team_id}"


def increment_request_count(team_id: int) -> None:
    try:
        client = get_client()
        time_bucket = str(int(time.time() / CACHE_BUCKET_SIZE))
        key_name = get_team_request_key(team_id)
        client.hincrby(key_name, time_bucket, 1)
    except Exception as error:
        capture_exception(error)


def capture_team_decide_usage(team_id: int, team_uuid: str) -> None:
    try:
        client = get_client()
        total_request_count = 0

        with client.lock(f"{REDIS_LOCK_TOKEN}:{team_id}", timeout=60, blocking=False):
            key_name = get_team_request_key(team_id)
            existing_values = client.hgetall(key_name)
            time_buckets = existing_values.keys()
            # The latest bucket is still being filled, so we don't want to delete it nor count it.
            # It will be counted in a later iteration, when it's not being filled anymore.
            if time_buckets and len(time_buckets) > 1:
                # redis returns encoded bytes, so we need to convert them into unix epoch for sorting
                for time_bucket in sorted(time_buckets, key=lambda bucket: int(bucket))[:-1]:
                    total_request_count += int(existing_values[time_bucket])
                    client.hdel(key_name, time_bucket)

            if total_request_count > 0:
                posthoganalytics.capture(
                    team_uuid,
                    "decide usage",
                    {"count": total_request_count, "team_id": team_id, "team_uuid": team_uuid},
                )

    except redis.exceptions.LockError:
        # lock wasn't acquired, which means another worker is working on this, so we don't need to do anything
        pass
    except Exception as error:
        capture_exception(error)
