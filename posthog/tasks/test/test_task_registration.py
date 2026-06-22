from typing import Any

import pytest

from django.test import TestCase

from posthog.celery import app


@pytest.mark.usefixtures("unittest_snapshot")
class TestAllTasksRegistered(TestCase):
    snapshot: Any

    def test_all_posthog_tasks_registered_snapshot(self) -> None:
        # Load the full task set the way a worker does (autodiscover + CELERY_IMPORTS)
        # rather than relying on whatever else this shard happened to import. Without
        # this the registry is complete only because item-level sharding imports the
        # whole tree; under --split-granularity=file a shard imports just its own files,
        # so non-tasks.py tasks (see CELERY_IMPORTS) would be missing and the snapshot
        # would silently lose entries.
        app.loader.import_default_modules()

        all_tasks = sorted([name for name in app.tasks.keys() if name.startswith("posthog.")])

        self.assertGreater(len(all_tasks), 0, "No PostHog tasks found. This likely indicates a registration problem.")

        assert all_tasks == self.snapshot
