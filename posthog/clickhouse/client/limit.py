import dataclasses
import time
from functools import wraps
from typing import Optional
from collections.abc import Callable

from celery import current_task
from prometheus_client import Counter

from posthog import redis

CONCURRENT_QUERY_LIMIT_EXCEEDED_COUNTER = Counter(
    "posthog_clickhouse_query_concurrency_limit_exceeded",
    "Number of times a ClickHouse query exceeded the concurrency limit",
    ["task_name", "limit", "limit_name"],
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
    Ensures that only max_concurrent_tasks of tasks_name are executed at a given time.
    Tasks have ttl as a safeguard against not being removed.
    """

    max_concurrent_tasks: int
    limit_name: str
    get_task_name: Callable
    get_task_id: Callable
    get_task_key: Optional[Callable] = None
    get_time: Callable[[], int] = lambda: int(time.time())
    applicable: Optional[Callable] = None  # allows to put a constraint on when rate limiting is used
    ttl: int = 60

    @property
    def redis_client(self):
        return redis.get_client()

    class Run:
        def __init__(self, limit, running_task_key, task_id):
            self.limit = limit
            self.running_task_key = running_task_key
            self.task_id = task_id

        def __enter__(self):
            pass

        def __exit__(self, applicable, running_task_key, task_id):
            if self.limit:
                self.limit.release(self.running_task_key, self.task_id)

    def run(self, *args, **kwargs):
        if self.applicable and not self.applicable(*args, **kwargs):
            return self.Run(None, None, None)
        running_tasks_key, task_id = self.use(*args, **kwargs)
        return self.Run(self, running_tasks_key, task_id)

    def use(self, *args, **kwargs):
        """
        Acquire the resource before execution or throw exception.
        """
        if self.applicable and not self.applicable(*args, **kwargs):
            return
        task_name = self.get_task_name(*args, **kwargs)
        running_tasks_key = self.get_task_key(*args, **kwargs) if self.get_task_key else task_name
        task_id = self.get_task_id(*args, **kwargs)
        current_time = self.get_time()

        # Atomically check, remove expired if limit hit, and add the new task
        if (
            self.redis_client.eval(
                lua_script, 1, running_tasks_key, current_time, task_id, self.max_concurrent_tasks, self.ttl
            )
            == 0
        ):
            CONCURRENT_QUERY_LIMIT_EXCEEDED_COUNTER.labels(
                task_name=task_name, limit=self.max_concurrent_tasks, limit_name=self.limit_name
            ).inc()

            raise ConcurrencyLimitExceeded(
                f"Exceeded maximum concurrent tasks limit: {self.max_concurrent_tasks} for key: {task_name} and task: {task_id}"
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
            applicable = self.applicable(*args, **kwargs) if self.applicable else True
            if applicable:
                running_tasks_key, task_id = self.use(*args, **kwargs)
            try:
                # Execute the task
                return task_func(*args, **kwargs)
            finally:
                # Remove the task ID from the sorted set when the task finishes
                if applicable:
                    self.release(running_tasks_key, task_id)

        return wrapper


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
