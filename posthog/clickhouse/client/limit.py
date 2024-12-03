import time
from functools import wraps
from typing import Optional
from collections.abc import Callable

from celery import current_task
from prometheus_client import Counter

from posthog import redis

CONCURRENT_TASKS_LIMIT_EXCEEDED_COUNTER = Counter(
    "posthog_celery_task_concurrency_limit_exceeded",
    "Number of times a Celery task exceeded the concurrency limit",
    ["task_name", "limit"],
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


class CeleryConcurrencyLimitExceeded(Exception):
    pass


def limit_concurrency(max_concurrent_tasks: int, key: Optional[Callable] = None, ttl: int = 60 * 15) -> Callable:
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
                CONCURRENT_TASKS_LIMIT_EXCEEDED_COUNTER.labels(task_name=task_name, limit=max_concurrent_tasks).inc()

                raise CeleryConcurrencyLimitExceeded(
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
