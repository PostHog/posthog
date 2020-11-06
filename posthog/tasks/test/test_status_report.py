from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import datetime, now
from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models import Dashboard, Event
from posthog.tasks.status_report import status_report
from posthog.version import VERSION


class TestStatusReport(BaseTest):
    TESTS_API = True

    @patch("os.environ", {"DEPLOYMENT": "tests"})
    def test_status_report(self) -> None:
        report = status_report(dry_run=True)

        self.assertEqual(report["posthog_version"], VERSION)
        self.assertEqual(report["deployment"], "tests")
        self.assertLess(report["table_sizes"]["posthog_event"], 10 ** 7)  # <10MB
        self.assertLess(report["table_sizes"]["posthog_sessionrecordingevent"], 10 ** 7)  # <10MB

    def test_team_status_report_event_counts(self) -> None:
        with freeze_time("2020-01-04T13:01:01Z"):
            self.create_event("$event1", "$web", now() - relativedelta(weeks=1, hours=2))
            self.create_event("$event2", "$web", now() - relativedelta(weeks=1, hours=1))
            self.create_event("$event2", "$mobile", now() - relativedelta(weeks=1, hours=1))
            self.create_event("$event3", "$mobile", now() - relativedelta(weeks=5))

            team_report = status_report(dry_run=True).get("teams")[self.team.id]  # type: ignore

            self.assertEqual(team_report["events_count_total"], 4)
            self.assertEqual(team_report["events_count_new_in_period"], 3)
            self.assertEqual(team_report["events_count_by_lib"], {"$mobile": 1, "$web": 2})
            self.assertEqual(team_report["events_count_by_name"], {"$event1": 1, "$event2": 2})

    def create_event(self, event: str, lib: str, created_at: datetime) -> None:
        Event.objects.create(
            team=self.team, event=event, timestamp=created_at, created_at=created_at, properties={"$lib": lib}
        )
