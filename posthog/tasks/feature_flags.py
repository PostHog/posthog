import json

import structlog
from celery import shared_task
from statshog.defaults.django import statsd

from posthog.models.feature_flag.local_evaluation import update_flag_caches
from posthog.models.team import Team
from posthog.redis import get_client
from posthog.settings.utils import get_from_env
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_flags_cache(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    update_flag_caches(team)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_all_flags_cache() -> None:
    # Meant to ensure we have all flags cache in sync in case something failed

    # Only select the id from the team queryset
    for team_id in Team.objects.values_list("id", flat=True):
        update_team_flags_cache.delay(team_id)


# Cache miss notification queue constants
CACHE_MISS_QUEUE_KEY = "posthog:flag_cache_miss_queue"
RATE_LIMIT_KEY_TEMPLATE = "posthog:flag_cache_rebuild_rate_limit:{team_id}"

# Configurable operational parameters
RATE_LIMIT_WINDOW = get_from_env("FLAG_CACHE_MISS_RATE_LIMIT_WINDOW", 60, type_cast=int)
MAX_REBUILDS_PER_WINDOW = get_from_env("FLAG_CACHE_MISS_MAX_REBUILDS", 2, type_cast=int)
BATCH_SIZE = get_from_env("FLAG_CACHE_MISS_BATCH_SIZE", 10, type_cast=int)
QUEUE_DEPTH_WARNING_THRESHOLD = get_from_env("FLAG_CACHE_MISS_QUEUE_DEPTH_WARNING", 1000, type_cast=int)


# Note: This task polls a Redis list (not a Celery queue), so the queue parameter
# only affects where this lightweight polling task runs. The polling work itself
# (RPOP + rate limit check) is minimal. Cache rebuilds are dispatched to separate
# update_team_flags_cache tasks which also run on DEFAULT queue.
@shared_task(ignore_result=True, max_retries=0, queue=CeleryQueue.DEFAULT.value)
def process_flag_cache_miss_queue() -> None:
    """
    Processes flag cache miss notifications from the Redis queue.

    This task is run periodically (every 1 second) by Celery Beat.
    It polls the Redis list for cache miss notifications from the Rust service,
    applies rate limiting, and dispatches cache rebuild tasks.

    Environment variables:
    - FLAG_CACHE_MISS_RATE_LIMIT_WINDOW: Rate limit window in seconds (default: 60)
    - FLAG_CACHE_MISS_MAX_REBUILDS: Max rebuilds per window per team (default: 2)
    - FLAG_CACHE_MISS_BATCH_SIZE: Max messages to process per run (default: 10)
    - FLAG_CACHE_MISS_QUEUE_DEPTH_WARNING: Queue depth warning threshold (default: 1000)
    """
    redis = get_client()

    # Monitor queue depth to detect potential issues
    queue_depth = redis.llen(CACHE_MISS_QUEUE_KEY)
    statsd.gauge("flag_cache_miss_queue_depth", queue_depth)

    if queue_depth > QUEUE_DEPTH_WARNING_THRESHOLD:
        logger.warning(
            "Cache miss queue depth is high",
            queue_depth=queue_depth,
            threshold=QUEUE_DEPTH_WARNING_THRESHOLD,
        )

    processed = 0
    rate_limited = 0
    dispatched = 0
    errors = 0

    for _ in range(BATCH_SIZE):
        message = redis.rpop(CACHE_MISS_QUEUE_KEY)
        if not message:
            break

        try:
            data = json.loads(message)
            team_id = data["team_id"]

            # Rate limiting - don't rebuild too frequently for same team
            rate_limit_key = RATE_LIMIT_KEY_TEMPLATE.format(team_id=team_id)

            # Increment counter and check if we're under the rate limit
            current_count = redis.incr(rate_limit_key)

            # Set expiry on first increment
            if current_count == 1:
                redis.expire(rate_limit_key, RATE_LIMIT_WINDOW)

            if current_count <= MAX_REBUILDS_PER_WINDOW:
                logger.info(
                    "Triggering cache rebuild from cache miss",
                    team_id=team_id,
                    timestamp=data.get("timestamp"),
                )
                update_team_flags_cache.delay(team_id)
                dispatched += 1
            else:
                logger.info(
                    "Rate limit exceeded, skipping cache rebuild",
                    team_id=team_id,
                    rate_limit=f"{current_count}/{MAX_REBUILDS_PER_WINDOW}",
                )
                rate_limited += 1

            processed += 1

        except Exception as e:
            logger.exception("Error processing cache miss notification", error=str(e), message=message)
            errors += 1

    # Record metrics
    if processed > 0:
        logger.info("Processed cache miss notifications", count=processed)
        statsd.incr("flag_cache_miss_queue_processed", processed)
    if dispatched > 0:
        statsd.incr("flag_cache_miss_queue_dispatched", dispatched)
    if rate_limited > 0:
        statsd.incr("flag_cache_miss_queue_rate_limited", rate_limited)
    if errors > 0:
        statsd.incr("flag_cache_miss_queue_errors", errors)
