import socket

from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from clickhouse_driver.errors import NetworkError, ServerException, SocketTimeoutError
from parameterized import parameterized

from posthog.async_migrations.definition import AsyncMigrationDefinition
from posthog.async_migrations.setup import (
    ALL_ASYNC_MIGRATIONS,
    ASYNC_MIGRATION_TO_DEPENDENCY,
    DEPENDENCY_TO_ASYNC_MIGRATION,
    setup_async_migrations,
)

# No pytest.mark.async_migrations here on purpose: the Core shards filter uses
# -m "not async_migrations", and this guards Django startup, so it must run there.

MIGRATION_NAME = "0001_test_startup"


class _Migration(AsyncMigrationDefinition):
    # Must be below FROZEN_POSTHOG_VERSION for the is_required() gate to be reached
    posthog_max_version = "1.0.0"

    def __init__(self, is_required_result):
        self._is_required_result = is_required_result

    def is_required(self) -> bool:
        if isinstance(self._is_required_result, BaseException):
            raise self._is_required_result
        return self._is_required_result


class TestSetupAsyncMigrations(SimpleTestCase):
    def setUp(self):
        super().setUp()
        # Stub out the Postgres touchpoints so the startup path under test needs no DB
        self._patch("posthog.async_migrations.setup.setup_model")
        self._patch("posthog.async_migrations.setup.get_all_completed_async_migrations", return_value=[])
        self._patch("posthog.async_migrations.setup.get_instance_setting", return_value=False)

    def _patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, is_required_result):
        # patch.dict restores the module-level dependency maps that setup writes into
        with (
            patch.dict(ALL_ASYNC_MIGRATIONS, {MIGRATION_NAME: _Migration(is_required_result)}, clear=True),
            patch.dict(ASYNC_MIGRATION_TO_DEPENDENCY),
            patch.dict(DEPENDENCY_TO_ASYNC_MIGRATION),
        ):
            setup_async_migrations()

    @parameterized.expand(
        [
            (NetworkError("Name or service not known"),),
            (SocketTimeoutError("timed out"),),
            (socket.gaierror("Name or service not known"),),
        ]
    )
    def test_unreachable_clickhouse_does_not_fail_startup(self, error):
        self._run(error)

    def test_required_migration_still_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            self._run(True)

    def test_clickhouse_query_error_still_raises(self):
        with self.assertRaises(ServerException):
            self._run(ServerException("Table doesn't exist", code=60))
