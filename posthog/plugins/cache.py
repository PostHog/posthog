import pickle
from typing import Any

from posthog.cache import get_redis_instance


class PluginCache:
    def __init__(self, scope: str):
        self.scope = scope
        self.redis = get_redis_instance()

    def format_key(self, key):
        key = "{scope}_{key}".format(scope=self.scope, key=key)
        return key

    def set(self, key: str, value: Any):
        if not self.redis:
            raise Exception("Redis not configured!")
        key = self.format_key(key)
        value = pickle.dumps(value)
        self.redis.set(key, value)

    def get(self, key) -> Any:
        if not self.redis:
            raise Exception("Redis not configured!")
        key = self.format_key(key)
        str_value = self.redis.get(key)
        if not str_value:
            return None
        value = pickle.loads(str_value)
        return value
