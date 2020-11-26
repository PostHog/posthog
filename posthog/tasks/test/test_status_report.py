from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import datetime, now
from freezegun import freeze_time

from posthog.models import Dashboard, Event, Person
from posthog.tasks.status_report import status_report
from posthog.test.base import BaseTest
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
        with freeze_time("2020-11-02"):
            self.create_person("old_user1")
            self.create_person("old_user2")

        with freeze_time("2020-11-10"):
            self.create_person("new_user1")
            self.create_person("new_user2")
            self.create_event("new_user1", "$event1", "$web", now() - relativedelta(weeks=1, hours=2))
            self.create_event("new_user1", "$event2", "$web", now() - relativedelta(weeks=1, hours=1))
            self.create_event("new_user1", "$event2", "$mobile", now() - relativedelta(weeks=1, hours=1))
            self.create_event("new_user1", "$event3", "$mobile", now() - relativedelta(weeks=5))

            team_report = status_report(dry_run=True).get("teams")[self.team.id]  # type: ignore

            self.assertEqual(team_report["events_count_total"], 4)
            self.assertEqual(team_report["events_count_new_in_period"], 3)
            self.assertEqual(team_report["events_count_by_lib"], {"$mobile": 1, "$web": 2})
            self.assertEqual(team_report["events_count_by_name"], {"$event1": 1, "$event2": 2})

            self.assertEqual(team_report["persons_count_total"], 4)
            self.assertEqual(team_report["persons_count_new_in_period"], 2)
            self.assertEqual(team_report["persons_count_active_in_period"], 1)

    def create_person(self, distinct_id: str) -> None:
        Person.objects.create(team=self.team, distinct_ids=[distinct_id])

    def create_event(self, distinct_id: str, event: str, lib: str, created_at: datetime) -> None:
        Event.objects.create(
            team=self.team,
            distinct_id=distinct_id,
            event=event,
            timestamp=created_at,
            created_at=created_at,
            properties={"$lib": lib},
        )
