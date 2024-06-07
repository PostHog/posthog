from functools import wraps
from typing import Optional
from collections.abc import Callable

from celery import current_task
from prometheus_client import Counter

from posthog import redis

# Lua script for atomic increment and check
lua_script = """
local current_count = redis.call('GET', KEYS[1])
if current_count and tonumber(current_count) >= tonumber(ARGV[1]) then
    return 0
else
    redis.call('INCR', KEYS[1])
    return 1
end
"""

CONCURRENT_TASKS_LIMIT_EXCEEDED_COUNTER = Counter(
    "celery_concurrent_tasks_limit_exceeded",
    "Number of times a Celery task exceeded the concurrency limit",
    ["task_name", "limit", "key"],
)


class CeleryConcurrencyLimitExceeded(Exception):
    pass


def limit_concurrency(max_concurrent_tasks: int, key: Optional[Callable] = None) -> Callable:
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

            # Atomically check and increment running task count
            if redis_client.eval(lua_script, 1, running_tasks_key, max_concurrent_tasks) == 0:
                CONCURRENT_TASKS_LIMIT_EXCEEDED_COUNTER.labels(
                    task_name=task_name, limit=max_concurrent_tasks, key=dynamic_key
                ).inc()

                raise CeleryConcurrencyLimitExceeded(
                    f"Exceeded maximum concurrent tasks limit: {max_concurrent_tasks} for key: {dynamic_key}"
                )

            try:
                # Execute the task
                return task_func(*args, **kwargs)
            finally:
                # Decrement counter when task finishes
                redis_client.decr(running_tasks_key)

        return wrapper

    return decorator
