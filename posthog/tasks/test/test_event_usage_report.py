from typing import Callable
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import datetime, now
from freezegun import freeze_time

from posthog.models import Event, Organization, Person, Plugin, Team
from posthog.models.plugin import PluginConfig
from posthog.models.utils import UUIDT
from posthog.tasks.event_usage_report import event_usage_report
from posthog.test.base import APIBaseTest
from posthog.utils import is_clickhouse_enabled
from posthog.version import VERSION


def factory_event_usage_report(_create_event: Callable, _create_person: Callable) -> "TestEventUsageReport":
    class TestEventUsageReport(APIBaseTest):
        def create_new_org_and_team(self, for_internal_metrics: bool = False) -> Team:
            org = Organization.objects.create(name="New Org", for_internal_metrics=for_internal_metrics)
            team = Team.objects.create(organization=org, name="Default Project")
            return team

        @patch("os.environ", {"DEPLOYMENT": "tests"})
        def test_event_usage_report(self) -> None:
            report = event_usage_report()

            self.assertEqual(report["posthog_version"], VERSION)
            self.assertEqual(report["deployment"], "tests")

        def test_event_counts(self) -> None:
            with freeze_time("2020-11-02"):
                _create_person("old_user1", team=self.team)
                _create_person("old_user2", team=self.team)

            with freeze_time("2020-11-11 12:00:00"):
                _create_person("new_user1", team=self.team)
                _create_person("new_user2", team=self.team)
                _create_event("new_user1", "$event1", "$web", now() - relativedelta(days=1, hours=2), team=self.team)
                _create_event("new_user1", "$event2", "$web", now() - relativedelta(days=1, hours=1), team=self.team)
                _create_event("new_user1", "$event2", "$mobile", now() - relativedelta(days=1, hours=1), team=self.team)
                _create_event("new_user1", "$event3", "$mobile", now() - relativedelta(weeks=5), team=self.team)

                org_report = event_usage_report().get("instance_usage_by_org")[str(self.team.organization.id)]

                def _test_org_report() -> None:
                    self.assertEqual(org_report["events_count_total"], 4)
                    self.assertEqual(org_report["events_count_new_in_period"], 3)
                    self.assertEqual(org_report["events_count_month_to_date"], 4)

                _test_org_report()

                # Create usage in a different org.
                team_in_other_org = self.create_new_org_and_team()
                _create_person("new_user1", team=team_in_other_org)
                _create_person("new_user2", team=team_in_other_org)
                _create_event(
                    "new_user1", "$event1", "$web", now() - relativedelta(days=1, hours=2), team=team_in_other_org
                )

                # Make sure the original team report is unchanged
                _test_org_report()

                # Create an event before and after this current period
                _create_event(
                    "new_user1", "$eventAfter", "$web", now() + relativedelta(days=2, hours=2), team=self.team
                )
                _create_event(
                    "new_user1", "$eventBefore", "$web", now() - relativedelta(days=2, hours=2), team=self.team
                )

                updated_org_report = event_usage_report().get("instance_usage_by_org")[str(self.team.organization.id)]

                # Check event totals are updated
                self.assertEqual(
                    updated_org_report["events_count_total"], org_report["events_count_total"] + 2,
                )

                # Check event usage in current period is unchanged
                self.assertEqual(
                    updated_org_report["events_count_new_in_period"], org_report["events_count_new_in_period"]
                )

                # Create an internal metrics org
                internal_metrics_team = self.create_new_org_and_team(for_internal_metrics=True)
                _create_person("new_user1", team=internal_metrics_team)
                _create_event(
                    "new_user1", "$event1", "$web", now() - relativedelta(days=1, hours=2), team=internal_metrics_team
                )
                _create_event(
                    "new_user1", "$event2", "$web", now() - relativedelta(days=1, hours=2), team=internal_metrics_team
                )
                _create_event(
                    "new_user1", "$event3", "$web", now() - relativedelta(days=1, hours=2), team=internal_metrics_team
                )
                # Verify that internal metrics events are not counted
                self.assertEqual(
                    event_usage_report().get("instance_usage_by_org")[str(self.team.organization.id)][
                        "events_count_total"
                    ],
                    updated_org_report["events_count_total"],
                )

    return TestEventUsageReport  # type: ignore


def create_person(distinct_id: str, team: Team) -> None:
    Person.objects.create(team=team, distinct_ids=[distinct_id])


def create_event(distinct_id: str, event: str, lib: str, created_at: datetime, team: Team) -> None:
    Event.objects.create(
        team=team,
        distinct_id=distinct_id,
        event=event,
        timestamp=created_at,
        created_at=created_at,
        properties={"$lib": lib},
    )


class TestEventUsageReport(factory_event_usage_report(create_event, create_person)):  # type: ignore
    pass
