from typing import List
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from ee.clickhouse.models.group import create_group
from posthog.models import Organization, Team, User
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.tasks.org_usage_report import OrgReport, send_all_reports
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from posthog.version import VERSION


class TestOrganizationUsageReport(APIBaseTest, ClickhouseTestMixin):
    def create_new_org_and_team(
        self, for_internal_metrics: bool = False, org_owner_email: str = "test@posthog.com"
    ) -> Team:
        org = Organization.objects.create(name="New Org", for_internal_metrics=for_internal_metrics)
        team = Team.objects.create(organization=org, name="Default Project")
        User.objects.create_and_join(
            organization=org, email=org_owner_email, password=None, level=OrganizationMembership.Level.OWNER
        )
        return team

    def select_report_by_org_id(self, org_id: str, reports: List[OrgReport]) -> OrgReport:
        return [report for report in reports if report["organization_id"] == org_id][0]

    @patch("os.environ", {"DEPLOYMENT": "tests"})
    def test_org_usage_report(self) -> None:
        all_reports = send_all_reports(dry_run=True)
        self.assertEqual(all_reports[0]["posthog_version"], VERSION)
        self.assertEqual(all_reports[0]["deployment_infrastructure"], "tests")
        self.assertIsNotNone(all_reports[0]["realm"])
        self.assertIsNotNone(all_reports[0]["site_url"])
        self.assertGreaterEqual(len(all_reports[0]["license_keys"]), 0)
        self.assertIsNotNone(all_reports[0]["product"])

    def test_event_counts(self) -> None:
        default_team = self.create_new_org_and_team()

        def _test_org_report(org_report: OrgReport) -> None:
            self.assertEqual(org_report["event_count_lifetime"], 5)
            self.assertEqual(org_report["event_count_in_period"], 3)
            self.assertEqual(org_report["event_count_in_month"], 4)
            self.assertIsNotNone(org_report["organization_id"])
            self.assertIsNotNone(org_report["organization_name"])
            self.assertIsNotNone(org_report["organization_created_at"])
            self.assertGreaterEqual(org_report["organization_user_count"], 1)
            self.assertEqual(org_report["team_count"], 1)
            self.assertEqual(org_report["group_types_total"], 0)
            self.assertEqual(org_report["event_count_with_groups_month"], 0)

        with self.settings(USE_TZ=False):
            with freeze_time("2020-11-02"):
                _create_person(distinct_ids=["old_user1"], team=default_team)
                _create_person(distinct_ids=["old_user2"], team=default_team)

            with freeze_time("2020-11-11 00:30:00"):
                _create_person(distinct_ids=["new_user1"], team=default_team)
                _create_person(distinct_ids=["new_user2"], team=default_team)
                _create_event(
                    distinct_id="new_user1",
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=12),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event2",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=11),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event2",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(hours=11),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event2",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(days=1, hours=1),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event3",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(weeks=5),
                    team=default_team,
                )

                all_reports = send_all_reports(dry_run=True)
                org_report = self.select_report_by_org_id(str(default_team.organization.id), all_reports)
                _test_org_report(org_report)

                # Create usage in a different org.
                team_in_other_org = self.create_new_org_and_team(org_owner_email="other@example.com")
                _create_person(distinct_ids=["new_user1"], team=team_in_other_org)
                _create_person(distinct_ids=["new_user2"], team=team_in_other_org)
                _create_event(
                    distinct_id="new_user1",
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=1, hours=2),
                    team=team_in_other_org,
                )

                # Make sure the original team report is unchanged
                _test_org_report(org_report)

                # Create an event before and after this current period
                _create_event(
                    distinct_id="new_user1",
                    event="$eventAfter",
                    properties={"$lib": "$web"},
                    timestamp=now() + relativedelta(days=2, hours=2),
                    team=default_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$eventBefore",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=2, hours=2),
                    team=default_team,
                )

                # Check event totals are updated
                updated_org_reports = send_all_reports(dry_run=True)
                updated_org_report = self.select_report_by_org_id(
                    str(default_team.organization.id), updated_org_reports
                )
                self.assertEqual(
                    updated_org_report["event_count_lifetime"], org_report["event_count_lifetime"] + 2,
                )

                # Check event usage in current period is unchanged
                self.assertEqual(updated_org_report["event_count_in_period"], org_report["event_count_in_period"])

                # Create an internal metrics org
                internal_metrics_team = self.create_new_org_and_team(
                    for_internal_metrics=True, org_owner_email="hey@posthog.com"
                )
                _create_person(distinct_ids=["new_user1"], team=internal_metrics_team)
                _create_event(
                    distinct_id="new_user1",
                    event="$event1",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=1, hours=2),
                    team=internal_metrics_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event2",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=1, hours=2),
                    team=internal_metrics_team,
                )
                _create_event(
                    distinct_id="new_user1",
                    event="$event3",
                    properties={"$lib": "$web"},
                    timestamp=now() - relativedelta(days=1, hours=2),
                    team=internal_metrics_team,
                )

                # Verify that internal metrics events are not counted
                org_reports_after_internal_org = send_all_reports(dry_run=True)
                org_report_after_internal_org = self.select_report_by_org_id(
                    str(default_team.organization.id), org_reports_after_internal_org
                )
                self.assertEqual(
                    org_report_after_internal_org["event_count_lifetime"], updated_org_report["event_count_lifetime"],
                )

    def test_groups_usage(self) -> None:
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})

        with freeze_time("2021-11-11 00:30:00"):
            _create_event(
                event="event",
                lib="web",
                distinct_id="user_1",
                team=self.team,
                timestamp="2021-11-10 02:00:00",
                properties={"$group_0": "org:5"},
            )
            _create_event(
                event="event",
                lib="web",
                distinct_id="user_1",
                team=self.team,
                timestamp="2021-11-10 05:00:00",
                properties={"$group_0": "org:6"},
            )

            _create_event(
                event="event", lib="web", distinct_id="user_7", team=self.team, timestamp="2021-11-10 10:00:00",
            )

            all_reports = send_all_reports(dry_run=True)
            org_report = self.select_report_by_org_id(str(self.organization.id), all_reports)

            self.assertEqual(org_report["group_types_total"], 2)
            self.assertEqual(org_report["event_count_in_month"], 3)
            self.assertEqual(org_report["event_count_with_groups_month"], 2)
