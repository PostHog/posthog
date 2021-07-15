from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import datetime, now
from freezegun import freeze_time

from posthog.models import Event, Organization, Person, Plugin, Team
from posthog.models.plugin import PluginConfig
from posthog.tasks.status_report import status_report
from posthog.test.base import APIBaseTest
from posthog.version import VERSION


class TestStatusReport(APIBaseTest):
    @patch("os.environ", {"DEPLOYMENT": "tests"})
    def test_status_report(self) -> None:
        report = status_report(dry_run=True)

        self.assertEqual(report["posthog_version"], VERSION)
        self.assertEqual(report["deployment"], "tests")
        self.assertLess(report["table_sizes"]["posthog_event"], 10 ** 7)  # <10MB
        self.assertLess(report["table_sizes"]["posthog_sessionrecordingevent"], 10 ** 7)  # <10MB

    def test_instance_status_report_event_counts(self) -> None:
        with freeze_time("2020-11-02"):
            self.create_person("old_user1", team=self.team)
            self.create_person("old_user2", team=self.team)

        with freeze_time("2020-11-10"):
            self.create_person("new_user1", team=self.team)
            self.create_person("new_user2", team=self.team)
            self.create_event("new_user1", "$event1", "$web", now() - relativedelta(weeks=1, hours=2), team=self.team)
            self.create_event("new_user1", "$event2", "$web", now() - relativedelta(weeks=1, hours=1), team=self.team)
            self.create_event(
                "new_user1", "$event2", "$mobile", now() - relativedelta(weeks=1, hours=1), team=self.team
            )
            self.create_event("new_user1", "$event3", "$mobile", now() - relativedelta(weeks=5), team=self.team)

            team_report = status_report(dry_run=True).get("teams")[self.team.id]  # type: ignore

            def _test_team_report() -> None:
                self.assertEqual(team_report["events_count_total"], 4)
                self.assertEqual(team_report["events_count_new_in_period"], 3)
                self.assertEqual(team_report["events_count_by_lib"], {"$mobile": 1, "$web": 2})
                self.assertEqual(team_report["events_count_by_name"], {"$event1": 1, "$event2": 2})
                self.assertEqual(team_report["persons_count_total"], 4)
                self.assertEqual(team_report["persons_count_new_in_period"], 2)
                self.assertEqual(team_report["persons_count_active_in_period"], 1)

            _test_team_report()

            # Create usage in a different org.
            team_in_other_org = self.create_new_org_and_team()
            self.create_person("new_user1", team=team_in_other_org)
            self.create_person("new_user2", team=team_in_other_org)
            self.create_event(
                "new_user1", "$event1", "$web", now() - relativedelta(weeks=1, hours=2), team=team_in_other_org
            )

            # Make sure the original team report is unchanged
            _test_team_report()

            instance_usage_summary = status_report(dry_run=True).get("instance_usage_summary")
            self.assertEqual(
                instance_usage_summary["events_count_new_in_period"],  # type: ignore
                team_report["events_count_new_in_period"] + 1,
            )
            self.assertEqual(
                instance_usage_summary["events_count_total"],  # type: ignore
                team_report["events_count_total"] + 1,
            )
            self.assertEqual(
                instance_usage_summary["persons_count_total"],  # type: ignore
                team_report["persons_count_total"] + 2,
            )
            self.assertEqual(
                instance_usage_summary["persons_count_new_in_period"],  # type: ignore
                team_report["persons_count_new_in_period"],
            )
            # Create an event before and after this current period
            self.create_event(
                "new_user1", "$eventBefore", "$web", now() + relativedelta(weeks=2, hours=2), team=self.team
            )
            self.create_event(
                "new_user1", "$eventAfter", "$web", now() - relativedelta(weeks=2, hours=2), team=self.team
            )

            updated_team_report = status_report(dry_run=True).get("teams")[self.team.id]  # type: ignore
            updated_instance_usage_summary = status_report(dry_run=True).get("instance_usage_summary")

            # Check event totals are updated
            self.assertEqual(
                updated_team_report["events_count_total"], team_report["events_count_total"] + 2,
            )
            self.assertEqual(
                updated_instance_usage_summary["events_count_total"],  # type: ignore
                instance_usage_summary["events_count_total"] + 2,  # type: ignore
            )

            # Check event usage in current period is unchanged
            self.assertEqual(
                updated_team_report["events_count_new_in_period"], team_report["events_count_new_in_period"]
            )
            self.assertEqual(
                updated_instance_usage_summary["events_count_new_in_period"],  # type: ignore
                instance_usage_summary["events_count_new_in_period"],  # type: ignore
            )

            # Create an internal metrics org
            internal_metrics_team = self.create_new_org_and_team(for_internal_metrics=True)
            self.create_person("new_user1", team=internal_metrics_team)
            self.create_event(
                "new_user1", "$event1", "$web", now() - relativedelta(weeks=1, hours=2), team=internal_metrics_team
            )
            self.create_event(
                "new_user1", "$event2", "$web", now() - relativedelta(weeks=1, hours=2), team=internal_metrics_team
            )
            self.create_event(
                "new_user1", "$event3", "$web", now() - relativedelta(weeks=1, hours=2), team=internal_metrics_team
            )
            # Verify that internal metrics events are not counted
            self.assertEqual(
                status_report(dry_run=True).get("teams")[self.team.id]["events_count_total"],  # type: ignore
                updated_team_report["events_count_total"],
            )
            self.assertEqual(
                status_report(dry_run=True).get("instance_usage_summary")["events_count_total"],  # type: ignore
                updated_instance_usage_summary["events_count_total"],  # type: ignore
            )

    def test_status_report_plugins(self) -> None:
        self._create_plugin("Installed but not enabled", False)
        self._create_plugin("Installed and enabled", True)
        report = status_report(dry_run=True)

        self.assertEqual(report["plugins_installed"], {"Installed but not enabled": 1, "Installed and enabled": 1})
        self.assertEqual(report["plugins_enabled"], {"Installed and enabled": 1})

    @staticmethod
    def create_person(distinct_id: str, team: Team) -> None:
        Person.objects.create(team=team, distinct_ids=[distinct_id])

    @staticmethod
    def create_new_org_and_team(for_internal_metrics: bool = False) -> Team:
        org = Organization.objects.create(name="New Org", for_internal_metrics=for_internal_metrics)
        team = Team.objects.create(organization=org, name="Default Project")
        return team

    @staticmethod
    def create_event(distinct_id: str, event: str, lib: str, created_at: datetime, team: Team) -> None:
        Event.objects.create(
            team=team,
            distinct_id=distinct_id,
            event=event,
            timestamp=created_at,
            created_at=created_at,
            properties={"$lib": lib},
        )

    def _create_plugin(self, name: str, enabled: bool) -> None:
        plugin = Plugin.objects.create(organization_id=self.team.organization.pk, name=name)
        PluginConfig.objects.create(plugin=plugin, enabled=enabled, order=1)
