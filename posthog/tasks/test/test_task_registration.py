from typing import Any

import pytest

from django.test import TestCase

from posthog.celery import app


@pytest.mark.usefixtures("unittest_snapshot")
class TestAllTasksRegistered(TestCase):
    snapshot: Any

    def test_all_posthog_tasks_registered_snapshot(self) -> None:
        all_tasks = sorted([name for name in app.tasks.keys() if name.startswith("posthog.")])

        assert len(all_tasks) > 0, "No PostHog tasks found. This likely indicates a registration problem."

        assert all_tasks == self.snapshot
