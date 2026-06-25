from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.async_migration import AsyncMigration, MigrationStatus


class AsyncMigrationBaseTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.patcher = patch("posthoganalytics.capture")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)


def create_async_migration(
    name="test1",
    description="my desc",
    posthog_min_version="1.0.0",
    posthog_max_version="100000.0.0",
    status=MigrationStatus.NotStarted,
):
    return AsyncMigration.objects.create(
        name=name,
        description=description,
        posthog_min_version=posthog_min_version,
        posthog_max_version=posthog_max_version,
        status=status,
    )
