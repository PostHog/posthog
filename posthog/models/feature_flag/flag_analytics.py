import time
from datetime import datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import Q

from posthog.clickhouse.client import sync_execute
from posthog.constants import FlagRequestType
from posthog.exceptions_capture import capture_exception
from posthog.helpers.dashboard_templates import add_enriched_insights_to_feature_flag_dashboard
from posthog.models import Team
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.redis import get_client, redis

if TYPE_CHECKING:
    from posthoganalytics import Posthog

REDIS_LOCK_TOKEN = "posthog:decide_analytics:lock"
CACHE_BUCKET_SIZE = 60 * 2  # duration in seconds

# :NOTE: When making changes here, make sure you run test_no_interference_between_different_types_of_new_incoming_increments
# locally. It's not included in CI because of tricky patching freeze time in thread issues.


def get_team_request_key(team_id: int, request_type: FlagRequestType) -> str:
    if request_type == FlagRequestType.DECIDE:
        return f"posthog:decide_requests:{team_id}"
    elif request_type == FlagRequestType.LOCAL_EVALUATION:
        return f"posthog:local_evaluation_requests:{team_id}"
    else:
        raise ValueError(f"Unknown request type: {request_type}")


def increment_request_count(
    team_id: int, count: int = 1, request_type: FlagRequestType = FlagRequestType.DECIDE
) -> None:
    try:
        client = get_client()
        time_bucket = str(int(time.time() / CACHE_BUCKET_SIZE))
        key_name = get_team_request_key(team_id, request_type)
        client.hincrby(key_name, time_bucket, count)
    except Exception as error:
        capture_exception(error)


def _extract_total_count_for_key_from_redis_hash(client: redis.Redis, key: str) -> tuple[int, int, int]:
    total_count = 0
    existing_values = client.hgetall(key)
    time_buckets = existing_values.keys()
    min_time = int(time.time())
    max_time = 0
    # The latest bucket is still being filled, so we don't want to delete it nor count it.
    # It will be counted in a later iteration, when it's not being filled anymore.
    if time_buckets and len(time_buckets) > 1:
        # redis returns encoded bytes, so we need to convert them into unix epoch for sorting
        for time_bucket in sorted(time_buckets, key=lambda bucket: int(bucket))[:-1]:
            min_time = min(min_time, int(time_bucket) * CACHE_BUCKET_SIZE)
            max_time = max(max_time, int(time_bucket) * CACHE_BUCKET_SIZE)
            total_count += int(existing_values[time_bucket])
            client.hdel(key, time_bucket)

    return total_count, min_time, max_time


def capture_usage_for_all_teams(ph_client: "Posthog") -> None:
    for team in Team.objects.exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True)).only("id", "uuid"):
        capture_team_decide_usage(ph_client, team.id, team.uuid)


def capture_team_decide_usage(ph_client: "Posthog", team_id: int, team_uuid: str) -> None:
    try:
        client = get_client()
        total_decide_request_count = 0
        total_local_evaluation_request_count = 0

        with client.lock(f"{REDIS_LOCK_TOKEN}:{team_id}", timeout=60, blocking=False):
            decide_key_name = get_team_request_key(team_id, FlagRequestType.DECIDE)
            (
                total_decide_request_count,
                min_time,
                max_time,
            ) = _extract_total_count_for_key_from_redis_hash(client, decide_key_name)

            if total_decide_request_count > 0 and settings.DECIDE_BILLING_ANALYTICS_TOKEN:
                ph_client.capture(
                    distinct_id=team_id,
                    event="decide usage",
                    properties={
                        "count": total_decide_request_count,
                        "team_id": team_id,
                        "team_uuid": team_uuid,
                        "min_time": min_time,
                        "max_time": max_time,
                        "token": settings.DECIDE_BILLING_ANALYTICS_TOKEN,
                    },
                )

            local_evaluation_key_name = get_team_request_key(team_id, FlagRequestType.LOCAL_EVALUATION)
            (
                total_local_evaluation_request_count,
                min_time,
                max_time,
            ) = _extract_total_count_for_key_from_redis_hash(client, local_evaluation_key_name)

            if total_local_evaluation_request_count > 0 and settings.DECIDE_BILLING_ANALYTICS_TOKEN:
                ph_client.capture(
                    distinct_id=team_id,
                    event="local evaluation usage",
                    properties={
                        "count": total_local_evaluation_request_count,
                        "team_id": team_id,
                        "team_uuid": team_uuid,
                        "min_time": min_time,
                        "max_time": max_time,
                        "token": settings.DECIDE_BILLING_ANALYTICS_TOKEN,
                    },
                )

    except redis.exceptions.LockError:
        # lock wasn't acquired, which means another worker is working on this, so we don't need to do anything
        pass
    except Exception as error:
        capture_exception(error)


def find_flags_with_enriched_analytics(begin: datetime, end: datetime):
    result = sync_execute(
        """
        SELECT team_id, JSONExtractString(properties, 'feature_flag') as flag_key
        FROM events
        WHERE timestamp between %(begin)s AND %(end)s AND event = '$feature_view'
        GROUP BY team_id, flag_key
    """,
        {"begin": begin, "end": end},
    )

    for row in result:
        team_id = row[0]
        flag_key = row[1]
        team = Team.objects.only("project_id").get(id=team_id)

        try:
            flag = FeatureFlag.objects.get(team__project_id=team.project_id, key=flag_key)
            if not flag.has_enriched_analytics:
                flag.has_enriched_analytics = True
                flag.save()
                if flag.usage_dashboard and not flag.usage_dashboard_has_enriched_insights:
                    add_enriched_insights_to_feature_flag_dashboard(flag, flag.usage_dashboard)
        except FeatureFlag.DoesNotExist:
            pass
        except Exception as e:
            capture_exception(e)
