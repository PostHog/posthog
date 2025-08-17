import json
import time
from typing import Optional
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import threading
from django.core.cache import cache
from posthoganalytics import capture_exception
from prometheus_client import Counter
import structlog

from posthog.models.team.team import Team
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)


DEFAULT_CACHE_MISS_TTL = 60 * 60 * 24  # 1 day - it will be invalidated by the daily sync
DEFAULT_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days


CACHE_SYNC_COUNTER = Counter(
    "posthog_hypercache_sync",
    "Number of times the hypercache cache sync task has been run",
    labelnames=["result", "namespace", "value"],
)

HYPERCACHE_CACHE_COUNTER = Counter(
    "posthog_hypercache_get_from_cache",
    "Metric tracking whether a hypercache was fetched from cache or not",
    labelnames=["result", "namespace", "value"],
)


_HYPER_CACHE_EMPTY_VALUE = "__missing__"


class HyperCacheStoreMissing:
    pass


# Custom key type for the hypercache
KeyType = Team | str | int


# Shared thread pool to reduce resource usage from multiple ThreadPoolExecutor instances
_S3_WRITE_EXECUTOR_LOCK = threading.Lock()
_S3_WRITE_EXECUTOR = None


def _get_s3_write_executor():
    """Get or create a shared ThreadPoolExecutor for S3 writes to reduce resource usage."""
    global _S3_WRITE_EXECUTOR
    if _S3_WRITE_EXECUTOR is None:
        with _S3_WRITE_EXECUTOR_LOCK:
            if _S3_WRITE_EXECUTOR is None:
                _S3_WRITE_EXECUTOR = ThreadPoolExecutor(
                    max_workers=4,  # Reasonable limit for S3 writes
                    thread_name_prefix="hypercache-s3-shared"
                )
    return _S3_WRITE_EXECUTOR


class HyperCache:
    """
    This is a helper cache for a standard model of multi-tier caching. It should be used for anything that is "client" facing - i.e. where SDKs will be calling in high volumes.
    The idea is simple - pre-cache every value we could possibly need. This might sound expensive but for read-heavy workloads it is a MUST.
    """

    def __init__(
        self,
        namespace: str,
        value: str,
        load_fn: Callable[[KeyType], dict | HyperCacheStoreMissing],
        token_based: bool = False,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        cache_miss_ttl: int = DEFAULT_CACHE_MISS_TTL,
        skip_s3_write: bool = False,
    ):
        self.namespace = namespace
        self.value = value
        self.load_fn = load_fn
        self.token_based = token_based
        self.cache_ttl = cache_ttl
        self.cache_miss_ttl = cache_miss_ttl
        self.skip_s3_write = skip_s3_write

    @staticmethod
    def team_from_key(key: KeyType) -> Team:
        if isinstance(key, Team):
            return key
        elif isinstance(key, str):
            return Team.objects.get(api_token=key)
        else:
            return Team.objects.get(id=key)

    def get_cache_key(self, key: KeyType) -> str:
        if self.token_based:
            if isinstance(key, Team):
                key = key.api_token
            return f"cache/team_tokens/{key}/{self.namespace}/{self.value}"
        else:
            if isinstance(key, Team):
                key = key.id
            return f"cache/teams/{key}/{self.namespace}/{self.value}"

    def get_from_cache(self, key: KeyType) -> dict | None:
        data, _ = self.get_from_cache_with_source(key)
        return data

    def get_from_cache_with_source(self, key: KeyType) -> tuple[dict | None, str]:
        cache_key = self.get_cache_key(key)
        data = cache.get(cache_key)

        if data:
            HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc()

            if data == _HYPER_CACHE_EMPTY_VALUE:
                return None, "redis"
            else:
                return json.loads(data), "redis"

        # Fallback to s3
        try:
            data = object_storage.read(cache_key)
            if data:
                response = json.loads(data)
                HYPERCACHE_CACHE_COUNTER.labels(result="hit_s3", namespace=self.namespace, value=self.value).inc()
                self._set_cache_value_redis(key, response)
                return response, "s3"
        except ObjectStorageError:
            pass

        # NOTE: This only applies to the django version - the dedicated service will rely entirely on the cache
        data = self.load_fn(key)

        if isinstance(data, HyperCacheStoreMissing):
            self._set_cache_value_redis(key, None)
            HYPERCACHE_CACHE_COUNTER.labels(result="missing", namespace=self.namespace, value=self.value).inc()
            return None, "db"

        self._set_cache_value_redis(key, data)
        HYPERCACHE_CACHE_COUNTER.labels(result="hit_db", namespace=self.namespace, value=self.value).inc()
        return data, "db"

    def update_cache(self, key: KeyType) -> bool:
        logger.info(f"Syncing {self.namespace} cache for team {key}")

        try:
            data = self.load_fn(key)
            self.set_cache_value(key, data)
            return True
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to sync {self.namespace} cache for team {key}", exception=str(e))
            CACHE_SYNC_COUNTER.labels(result="failure", namespace=self.namespace, value=self.value).inc()
            return False

    def set_cache_value(self, key: KeyType, data: dict | None | HyperCacheStoreMissing) -> None:
        # Write to Redis synchronously for immediate availability
        self._set_cache_value_redis(key, data)
        # Write to S3 asynchronously to reduce latency impact, but only if not disabled
        if not self.skip_s3_write:
            self._set_cache_value_s3_async(key, data)
        else:
            logger.debug(
                "hypercache_s3_write_skipped",
                namespace=self.namespace,
                value=self.value,
                cache_key=self.get_cache_key(key)
            )

    def clear_cache(self, key: KeyType, kinds: Optional[list[str]] = None):
        """
        Only meant for use in tests
        """
        kinds = kinds or ["redis", "s3"]
        if "redis" in kinds:
            cache.delete(self.get_cache_key(key))
        if "s3" in kinds:
            object_storage.delete(self.get_cache_key(key))

    def _set_cache_value_redis(self, key: KeyType, data: dict | None | HyperCacheStoreMissing):
        key = self.get_cache_key(key)
        if data is None or isinstance(data, HyperCacheStoreMissing):
            cache.set(key, _HYPER_CACHE_EMPTY_VALUE, timeout=DEFAULT_CACHE_MISS_TTL)
        else:
            cache.set(key, json.dumps(data), timeout=DEFAULT_CACHE_TTL)

    def _set_cache_value_s3(self, key: KeyType, data: dict | None | HyperCacheStoreMissing):
        key = self.get_cache_key(key)
        if data is None or isinstance(data, HyperCacheStoreMissing):
            object_storage.delete(key)
        else:
            object_storage.write(key, json.dumps(data))
    
    def _set_cache_value_s3_async(self, key: KeyType, data: dict | None | HyperCacheStoreMissing) -> None:
        """Asynchronously write to S3 to avoid blocking Redis writes"""
        def _s3_write_task():
            start_time = time.time()
            try:
                self._set_cache_value_s3(key, data)
                write_duration = (time.time() - start_time) * 1000  # Convert to milliseconds
                logger.debug(
                    "hypercache_s3_async_write_success",
                    namespace=self.namespace,
                    value=self.value,
                    cache_key=self.get_cache_key(key),
                    write_duration_ms=write_duration
                )
            except ObjectStorageError as e:
                # More specific handling for S3 errors
                write_duration = (time.time() - start_time) * 1000
                logger.error(
                    "hypercache_s3_async_write_storage_error",
                    namespace=self.namespace,
                    value=self.value,
                    cache_key=self.get_cache_key(key),
                    error_type=type(e).__name__,
                    error=str(e),
                    write_duration_ms=write_duration,
                    data_present=data is not None and not isinstance(data, HyperCacheStoreMissing),
                    operation="s3_write",
                    aws_error_code=getattr(e, 'response', {}).get('Error', {}).get('Code', 'unknown') if hasattr(e, 'response') else 'unknown',
                    http_status_code=getattr(e, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode', 0) if hasattr(e, 'response') else 0
                )
                capture_exception(e, extra_data={
                    "namespace": self.namespace,
                    "value": self.value,
                    "cache_key": self.get_cache_key(key),
                    "operation": "hypercache_s3_async_write",
                    "write_duration_ms": write_duration,
                    "aws_error_code": getattr(e, 'response', {}).get('Error', {}).get('Code', 'unknown') if hasattr(e, 'response') else 'unknown',
                    "http_status_code": getattr(e, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode', 0) if hasattr(e, 'response') else 0,
                    "request_id": getattr(e, 'response', {}).get('ResponseMetadata', {}).get('RequestId', 'unknown') if hasattr(e, 'response') else 'unknown'
                })
            except Exception as e:
                # General exception handling
                write_duration = (time.time() - start_time) * 1000
                logger.error(
                    "hypercache_s3_async_write_failed",
                    namespace=self.namespace,
                    value=self.value,
                    cache_key=self.get_cache_key(key),
                    error_type=type(e).__name__,
                    error=str(e),
                    write_duration_ms=write_duration,
                    data_present=data is not None and not isinstance(data, HyperCacheStoreMissing),
                    stack_trace=str(e.__traceback__) if hasattr(e, '__traceback__') else None
                )
                capture_exception(e, extra_data={
                    "namespace": self.namespace,
                    "value": self.value,
                    "cache_key": self.get_cache_key(key),
                    "operation": "hypercache_s3_async_write",
                    "write_duration_ms": write_duration
                })
        
        # Use shared thread pool instead of creating new ones to reduce resource usage
        executor = _get_s3_write_executor()
        try:
            future = executor.submit(_s3_write_task)
            # Add callback for error logging if the future fails
            def _handle_future_result(f):
                try:
                    f.result(timeout=0.1)  # Short timeout to avoid blocking
                except Exception as e:
                    logger.warning(
                        "hypercache_s3_async_future_exception",
                        namespace=self.namespace,
                        value=self.value,
                        cache_key=self.get_cache_key(key),
                        error_type=type(e).__name__,
                        error=str(e)
                    )
            future.add_done_callback(_handle_future_result)
        except Exception as e:
            logger.error(
                "hypercache_s3_async_submit_failed",
                namespace=self.namespace,
                value=self.value,
                cache_key=self.get_cache_key(key),
                error_type=type(e).__name__,
                error=str(e),
                executor_state="shared_pool"
            )
            capture_exception(e, extra_data={
                "namespace": self.namespace,
                "value": self.value,
                "cache_key": self.get_cache_key(key),
                "operation": "hypercache_s3_async_submit"
            })
