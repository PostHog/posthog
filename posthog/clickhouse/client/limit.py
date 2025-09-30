import time
import uuid
import dataclasses
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from time import sleep
from typing import Optional

from celery import current_task
from prometheus_client import Counter

from posthog import redis, settings
from posthog.clickhouse.cluster import ExponentialBackoff
from posthog.constants import AvailableFeature
from posthog.settings import TEST
from posthog.utils import generate_short_id

# Default concurrency limits
DEFAULT_APP_ORG_CONCURRENT_QUERIES = 20
DEFAULT_APP_DASHBOARD_CONCURRENT_QUERIES = 6

CONCURRENT_QUERY_LIMIT_EXCEEDED_COUNTER = Counter(
    "posthog_clickhouse_query_concurrency_limit_exceeded",
    "Number of times a team tried to exceed concurrency limit.",
    ["task_name", "team_id", "limit", "limit_name", "result"],
)

CONCURRENT_TASKS_LIMIT_EXCEEDED_COUNTER = Counter(
    "posthog_celery_task_concurrency_limit_exceeded",
    "Number of times a Celery task exceeded the concurrency limit",
    ["task_name", "limit", "limit_name"],
)

# Lua script for atomic check, remove expired if limit hit, and increment with TTL
lua_script = """
local key = KEYS[1]
local current_time = tonumber(ARGV[1])
local task_id = ARGV[2]
local max_concurrent_tasks = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local expiration_time = current_time + ttl

-- Check the number of current running tasks
local running_tasks_count = redis.call('ZCARD', key)
if running_tasks_count >= max_concurrent_tasks then
    -- Remove expired tasks if limit is hit
    redis.call('ZREMRANGEBYSCORE', key, '-inf', current_time)
    running_tasks_count = redis.call('ZCARD', key)
    if running_tasks_count >= max_concurrent_tasks then
        return 0
    end
end

-- Add the new task with its expiration time
redis.call('ZADD', key, expiration_time, task_id)
return 1
"""


@dataclasses.dataclass
class RateLimit:
    """
    Ensures that only max_concurrency of tasks_name are executed at a given time.
    Tasks have ttl as a safeguard against not being removed.
    """

    max_concurrency: int
    limit_name: str
    get_task_name: Callable
    get_task_id: Callable
    get_task_key: Optional[Callable] = None
    applicable: Optional[Callable] = None  # allows to put a constraint on when rate limiting is used
    ttl: int = 60
    bypass_all: bool = False
    redis_client = redis.get_client()
    retry: Optional[float] = None
    retry_timeout: float = 10.0  # seconds
    get_time: Callable[[], float] = lambda: time.time()
    sleep: Callable[[float], None] = lambda d: sleep(d)

    @contextmanager
    def run(self, *args, **kwargs):
        applicable = not self.applicable or self.applicable(*args, **kwargs)

        if applicable:
            running_task_key, task_id = self.use(*args, **kwargs)

        try:
            yield
        finally:
            if applicable and running_task_key and task_id:
                self.release(running_task_key, task_id)

    def use(self, *args, **kwargs) -> tuple[Optional[str], Optional[str]]:
        """
        Acquire the resource before execution or throw exception.
        """
        wait_deadline = self.get_time() + self.retry_timeout
        task_name = self.get_task_name(*args, **kwargs)
        running_tasks_key = self.get_task_key(*args, **kwargs) if self.get_task_key else task_name
        task_id = self.get_task_id(*args, **kwargs)
        team_id: Optional[int] = kwargs.get("team_id", None)

        max_concurrency: int = self.max_concurrency

        in_beta = kwargs.get("is_api") and (team_id in settings.API_QUERIES_PER_TEAM)
        if in_beta:
            max_concurrency = settings.API_QUERIES_PER_TEAM[team_id]  # type: ignore
        elif "limit" in kwargs:
            limit_value = kwargs.get("limit")
            if limit_value is not None:
                max_concurrency = int(limit_value)

        # p80 is below 1.714ms, therefore max retry is 1.714s
        backoff = ExponentialBackoff(self.retry or 0.15, max_delay=1.714, exp=1.5)
        count = 1
        # Atomically check, remove expired if limit hit, and add the new task
        while (
            self.redis_client.eval(
                lua_script, 1, running_tasks_key, int(self.get_time()), task_id, max_concurrency, self.ttl
            )
            == 0
        ):
            from posthog.rate_limit import team_is_allowed_to_bypass_throttle

            bypass = team_is_allowed_to_bypass_throttle(team_id)

            # team in beta cannot skip limits
            if bypass or (not in_beta and self.bypass_all):
                result = "allow" if bypass else "block"
                CONCURRENT_QUERY_LIMIT_EXCEEDED_COUNTER.labels(
                    task_name=task_name,
                    team_id=str(team_id),
                    limit=max_concurrency,
                    limit_name=self.limit_name,
                    result=result,
                ).inc()
                return None, None

            if self.retry and self.get_time() < wait_deadline:
                CONCURRENT_QUERY_LIMIT_EXCEEDED_COUNTER.labels(
                    task_name=task_name,
                    team_id=str(team_id),
                    limit=max_concurrency,
                    limit_name=self.limit_name,
                    result="retry",
                ).inc()
                self.sleep(backoff(count))
                count += 1
                continue

            CONCURRENT_QUERY_LIMIT_EXCEEDED_COUNTER.labels(
                task_name=task_name,
                team_id=str(team_id),
                limit=max_concurrency,
                limit_name=self.limit_name,
                result="block",
            ).inc()

            raise ConcurrencyLimitExceeded(
                f"Exceeded maximum concurrency limit: {max_concurrency} for key: {task_name} and task: {task_id}"
            )

        return running_tasks_key, task_id

    def release(self, running_task_key, task_id):
        """
        Release the resource, when the execution finishes.
        """
        self.redis_client.zrem(running_task_key, task_id)

    def wrap(self, task_func):
        @wraps(task_func)
        def wrapper(*args, **kwargs):
            with self.run(*args, **kwargs):
                return task_func(*args, **kwargs)

        return wrapper


__API_CONCURRENT_QUERY_PER_TEAM: Optional[RateLimit] = None
__APP_CONCURRENT_QUERY_PER_ORG: Optional[RateLimit] = None
__APP_CONCURRENT_DASHBOARD_QUERIES_PER_ORG: Optional[RateLimit] = None
__WEB_ANALYTICS_API_CONCURRENT_QUERY_PER_TEAM: Optional[RateLimit] = None


def get_api_team_rate_limiter():
    global __API_CONCURRENT_QUERY_PER_TEAM

    def __applicable(
        *args,
        team_id: Optional[int] = None,
        is_api: Optional[bool] = None,
        **kwargs,
    ) -> bool:
        return bool(
            not TEST
            and is_api
            and team_id
            and (
                team_id in settings.API_QUERIES_PER_TEAM
                or (settings.API_QUERIES_LEGACY_TEAM_LIST and team_id not in settings.API_QUERIES_LEGACY_TEAM_LIST)
            )
        )

    if __API_CONCURRENT_QUERY_PER_TEAM is None:
        __API_CONCURRENT_QUERY_PER_TEAM = RateLimit(
            max_concurrency=3,
            applicable=__applicable,
            limit_name="api_per_team",
            get_task_name=lambda *args, **kwargs: f"api:query:per-team:{kwargs.get('team_id')}",
            get_task_id=lambda *args, **kwargs: (
                current_task.request.id if current_task else (kwargs.get("task_id") or generate_short_id())
            ),
            ttl=600,
            # p20 duration for a query is 133ms, p25 is 164ms, p50 is 458ms, there's a 20% chance that after 134ms
            # the slot is free.
            retry=0.134,
            # The default timeout for a query on ClickHouse is 60s. p99 duration is 19s, 30 seconds should be enough
            # for some other query to finish. If the query cannot get a slot in this period, the user should contact us
            # about increasing the quota.
            retry_timeout=30.0,
        )
    return __API_CONCURRENT_QUERY_PER_TEAM


def get_app_org_rate_limiter():
    """
    Limits the number of concurrent queries (running outside celery) per organization.
    """
    global __APP_CONCURRENT_QUERY_PER_ORG
    if __APP_CONCURRENT_QUERY_PER_ORG is None:
        __APP_CONCURRENT_QUERY_PER_ORG = RateLimit(
            max_concurrency=DEFAULT_APP_ORG_CONCURRENT_QUERIES,
            applicable=lambda *args, **kwargs: (
                not TEST
                and kwargs.get("org_id")
                and not kwargs.get("is_api")
                # if running in celery, we don't want rate limit to apply
                # as celery tasks have their own limits on the queues + using @limit_concurrency
                and not current_task
            ),
            limit_name="app_per_org",
            get_task_name=lambda *args, **kwargs: f"app:query:per-org:{kwargs.get('org_id')}",
            get_task_id=lambda *args, **kwargs: kwargs.get("task_id") or generate_short_id(),
            ttl=600,
        )
    return __APP_CONCURRENT_QUERY_PER_ORG


def get_app_dashboard_queries_rate_limiter():
    """
    Limits the number of concurrent queries (running outside celery) per organization.
    """
    global __APP_CONCURRENT_DASHBOARD_QUERIES_PER_ORG
    if __APP_CONCURRENT_DASHBOARD_QUERIES_PER_ORG is None:
        __APP_CONCURRENT_DASHBOARD_QUERIES_PER_ORG = RateLimit(
            max_concurrency=DEFAULT_APP_DASHBOARD_CONCURRENT_QUERIES,
            applicable=(
                lambda *args, **kwargs: not TEST
                and not kwargs.get("is_api")
                and kwargs.get("dashboard_id") is not None
                # if running in celery, we don't want rate limit to apply
                # as celery tasks have their own limits on the queues + using @limit_concurrency
                and not current_task
            ),
            limit_name="app_dashboard_queries_per_org",
            get_task_name=lambda *args, **kwargs: f"app:dashboard_query:per-org:{kwargs.get('org_id')}",
            get_task_id=lambda *args, **kwargs: kwargs.get("task_id") or generate_short_id(),
            ttl=600,
        )
    return __APP_CONCURRENT_DASHBOARD_QUERIES_PER_ORG


def get_web_analytics_api_rate_limiter():
    """
    Limits the number of concurrent web analytics API queries per team.
    """
    global __WEB_ANALYTICS_API_CONCURRENT_QUERY_PER_TEAM

    def __applicable(
        *args,
        team_id: Optional[int] = None,
        **kwargs,
    ) -> bool:
        return bool(not TEST and team_id)

    if __WEB_ANALYTICS_API_CONCURRENT_QUERY_PER_TEAM is None:
        __WEB_ANALYTICS_API_CONCURRENT_QUERY_PER_TEAM = RateLimit(
            max_concurrency=3,
            applicable=__applicable,
            limit_name="web_analytics_api_per_team",
            get_task_name=lambda *args, **kwargs: f"web_analytics_api:query:per-team:{kwargs.get('team_id')}",
            get_task_id=lambda *args, **kwargs: (
                current_task.request.id if current_task else (kwargs.get("task_id") or generate_short_id())
            ),
            ttl=600,
            retry=0.134,
            retry_timeout=30.0,
        )
    return __WEB_ANALYTICS_API_CONCURRENT_QUERY_PER_TEAM


class ConcurrencyLimitExceeded(Exception):
    pass


def limit_concurrency(
    max_concurrent_tasks: int, key: Optional[Callable] = None, ttl: int = 60 * 15, limit_name: str = ""
) -> Callable:
    def decorator(task_func):
        @wraps(task_func)
        def wrapper(*args, **kwargs):
            task_name = current_task.name
            redis_client = redis.get_client()
            running_tasks_key = f"celery_running_tasks:{task_name}"
            if key:
                dynamic_key = key(*args, **kwargs)
                running_tasks_key = f"{running_tasks_key}:{dynamic_key}"
            else:
                dynamic_key = None
            task_id = f"{task_name}:{current_task.request.id}"
            current_time = int(time.time())

            # Atomically check, remove expired if limit hit, and add the new task
            if (
                redis_client.eval(lua_script, 1, running_tasks_key, current_time, task_id, max_concurrent_tasks, ttl)
                == 0
            ):
                CONCURRENT_TASKS_LIMIT_EXCEEDED_COUNTER.labels(
                    task_name=task_name, limit=max_concurrent_tasks, limit_name=limit_name
                ).inc()

                raise ConcurrencyLimitExceeded(
                    f"Exceeded maximum concurrent tasks limit: {max_concurrent_tasks} for key: {dynamic_key}"
                )

            try:
                # Execute the task
                return task_func(*args, **kwargs)
            finally:
                # Remove the task ID from the sorted set when the task finishes
                redis_client.zrem(running_tasks_key, task_id)

        return wrapper

    return decorator


def get_org_app_concurrency_limit(org_id: uuid.UUID) -> Optional[int]:
    """
    Get organization concurrency limit for app queries from
    feature entitlements. Using Redis for quicker lookups.
    Returns None if no org-specific limit is found.
    """
    cache_key = f"org_app_concurrency_limit:{org_id}"
    cached_limit = redis.get_client().get(cache_key)
    if cached_limit:
        return int(cached_limit)

    try:
        from posthog.models.organization import Organization

        org = Organization.objects.get(id=org_id)
        feature = org.get_available_feature(AvailableFeature.ORGANIZATION_APP_QUERY_CONCURRENCY_LIMIT)
        if feature and isinstance(feature.get("limit"), int):
            limit = feature["limit"]
            # Cache for 1 hour
            redis.get_client().setex(cache_key, 3600, limit)
            return limit
    except Exception:
        # Fall back to default if anything goes wrong
        pass

    return None
