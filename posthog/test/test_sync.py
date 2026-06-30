from concurrent.futures import ThreadPoolExecutor

import pytest

from asgiref.sync import SyncToAsync

import posthog.sync as sync_module
from posthog.sync import database_sync_to_async_pool, get_database_sync_to_async_pool_executor


@pytest.fixture(autouse=True)
def _reset_pool_executor():
    # The executor is memoized process-wide; reset around each test so size assertions are isolated.
    original = sync_module._pool_executor
    sync_module._pool_executor = None
    yield
    sync_module._pool_executor = original


def test_pool_executor_is_bounded_by_setting(settings):
    settings.DATABASE_SYNC_TO_ASYNC_POOL_MAX_WORKERS = 7
    executor = get_database_sync_to_async_pool_executor()
    assert isinstance(executor, ThreadPoolExecutor)
    assert executor._max_workers == 7


def test_pool_executor_is_shared_across_calls():
    assert get_database_sync_to_async_pool_executor() is get_database_sync_to_async_pool_executor()


def test_database_sync_to_async_pool_uses_bounded_executor():
    # Without this, asgiref's thread_sensitive=False path falls through to the event loop's
    # unbounded default executor, letting each activity open its own Postgres connection.
    wrapped = database_sync_to_async_pool(lambda: None)
    assert isinstance(wrapped, SyncToAsync)
    assert wrapped._executor is get_database_sync_to_async_pool_executor()


def test_database_sync_to_async_pool_respects_explicit_executor():
    custom = ThreadPoolExecutor(max_workers=1)
    wrapped = database_sync_to_async_pool(lambda: None, executor=custom)
    assert wrapped._executor is custom
    custom.shutdown(wait=False)
