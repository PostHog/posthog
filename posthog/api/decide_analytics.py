from posthog.models import Team
from posthog import redis
import time
import posthoganalytics
from sentry_sdk import capture_exception

REDIS_LOCK_TOKEN = "posthog/decide_analytics/lock"


def get_team_request_key(team: Team) -> str:
    return f"posthog/decide_requests/{team.pk}"


def increment_request_count(team: Team) -> None:
    try:
        client = redis.get_client()
        time_bucket = str(int(time.time() / 60))
        key_name = get_team_request_key(team)
        client.hincrby(key_name, time_bucket, 1)
    except Exception as error:
        capture_exception(error)


def capture_team_decide_usage(team: Team) -> None:
    try:
        client = redis.get_client()
        total_request_count = 0

        # TODO: Figure out if this lock prevents decide request increments?
        # It shouldn't, given how redis locks work.
        with client.lock(REDIS_LOCK_TOKEN, timeout=60, blocking_timeout=60):
            key_name = get_team_request_key(team)
            existing_values = client.hgetall(key_name)
            time_buckets = existing_values.keys()
            if time_buckets and len(time_buckets) > 1:
                # The latest bucket is still being filled, so we don't want to delete it nor count it.
                for time_bucket in sorted(time_buckets)[:-1]:
                    total_request_count += int(existing_values[time_bucket])
                    client.hdel(key_name, time_bucket)

            if total_request_count > 0:
                posthoganalytics.capture(team.id, "decide usage", {"count": total_request_count})

    except redis.LockError:
        # lock wasn't acquired, so another worker is working on this, so we don't need to do anything
        pass
    except Exception as error:
        capture_exception(error)
