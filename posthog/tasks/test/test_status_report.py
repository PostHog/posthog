from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models import Dashboard
from posthog.tasks.status_report import status_report


class TestStatusReport(BaseTest):
    TESTS_API = True

    def test_sttus_report(self) -> None:
        with freeze_time("2020-01-04T13:01:01Z"):
            status_report(dry_run=True)
