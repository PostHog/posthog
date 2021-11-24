from typing import Any, Callable, Dict, List
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import datetime, now
from freezegun import freeze_time

from posthog.models import Event, FeatureFlag, Organization, Person, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.models.session_recording_event import SessionRecordingEvent
from posthog.tasks.org_usage_report import OrgReport, send_all_org_usage_reports
from posthog.test.base import APIBaseTest
from posthog.version import VERSION


def factory_org_usage_report(
    _create_person: Callable,
    _create_event: Callable,
    _create_session_recording: Callable,
    _send_all_org_usage_reports: Callable,
    _instance_settings: Dict[str, Any],
) -> "TestOrganizationUsageReport":
    class TestOrganizationUsageReport(APIBaseTest):
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
            all_reports = _send_all_org_usage_reports(dry_run=True)
            self.assertEqual(all_reports[0]["posthog_version"], VERSION)
            self.assertEqual(all_reports[0]["deployment_infrastructure"], "tests")
            self.assertIsNotNone(all_reports[0]["realm"])
            self.assertIsNotNone(all_reports[0]["is_clickhouse_enabled"])
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

            with self.settings(**_instance_settings):
                with freeze_time("2020-11-02"):
                    _create_person("old_user1", team=default_team)
                    _create_person("old_user2", team=default_team)

                with freeze_time("2020-11-11 00:30:00"):
                    _create_person("new_user1", team=default_team)
                    _create_person("new_user2", team=default_team)
                    _create_event("new_user1", "$event1", "$web", now() - relativedelta(hours=12), team=default_team)
                    _create_event("new_user1", "$event2", "$web", now() - relativedelta(hours=11), team=default_team)
                    _create_event("new_user1", "$event2", "$web", now() - relativedelta(hours=11), team=default_team)
                    _create_event(
                        "new_user1", "$event2", "$mobile", now() - relativedelta(days=1, hours=1), team=default_team
                    )
                    _create_event("new_user1", "$event3", "$mobile", now() - relativedelta(weeks=5), team=default_team)

                    all_reports = _send_all_org_usage_reports(dry_run=True)
                    org_report = self.select_report_by_org_id(str(default_team.organization.id), all_reports)
                    _test_org_report(org_report)

                    # Create usage in a different org.
                    team_in_other_org = self.create_new_org_and_team(org_owner_email="other@example.com")
                    _create_person("new_user1", team=team_in_other_org)
                    _create_person("new_user2", team=team_in_other_org)
                    _create_event(
                        "new_user1", "$event1", "$web", now() - relativedelta(days=1, hours=2), team=team_in_other_org
                    )

                    # Make sure the original team report is unchanged
                    _test_org_report(org_report)

                    # Create an event before and after this current period
                    _create_event(
                        "new_user1", "$eventAfter", "$web", now() + relativedelta(days=2, hours=2), team=default_team,
                    )
                    _create_event(
                        "new_user1", "$eventBefore", "$web", now() - relativedelta(days=2, hours=2), team=default_team
                    )

                    # Check event totals are updated
                    updated_org_reports = _send_all_org_usage_reports(dry_run=True)
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
                    _create_person("new_user1", team=internal_metrics_team)
                    _create_event(
                        "new_user1",
                        "$event1",
                        "$web",
                        now() - relativedelta(days=1, hours=2),
                        team=internal_metrics_team,
                    )
                    _create_event(
                        "new_user1",
                        "$event2",
                        "$web",
                        now() - relativedelta(days=1, hours=2),
                        team=internal_metrics_team,
                    )
                    _create_event(
                        "new_user1",
                        "$event3",
                        "$web",
                        now() - relativedelta(days=1, hours=2),
                        team=internal_metrics_team,
                    )

                    # Verify that internal metrics events are not counted
                    org_reports_after_internal_org = _send_all_org_usage_reports(dry_run=True)
                    org_report_after_internal_org = self.select_report_by_org_id(
                        str(default_team.organization.id), org_reports_after_internal_org
                    )
                    self.assertEqual(
                        org_report_after_internal_org["event_count_lifetime"],
                        updated_org_report["event_count_lifetime"],
                    )

                    # Create an event in the previous month
                    _create_event("new_user1", "$event1", "$web", now() - relativedelta(months=1), team=default_team)
                    org_reports_with_previous = _send_all_org_usage_reports(dry_run=True)
                    org_report_with_previous = self.select_report_by_org_id(
                        str(default_team.organization.id), org_reports_with_previous
                    )

                    # Create another event in the previous month, outside the current period
                    _create_event(
                        "new_user1",
                        "$event2",
                        "$web",
                        (now() - relativedelta(months=1)).replace(day=20),
                        team=default_team,
                    )
                    org_reports_with_previous = _send_all_org_usage_reports(dry_run=True)
                    org_report_with_previous = self.select_report_by_org_id(
                        str(default_team.organization.id), org_reports_with_previous
                    )

                    # Expected count is the difference between events in the current month-to-date
                    # and last month at current day (should count 1 event, not 2)
                    expected_count = org_report_with_previous["event_count_in_month"] - 1
                    self.assertEqual(
                        org_report_with_previous["event_count_in_month_vs_previous"], expected_count,
                    )

                    # Create a feature flag and verify the count
                    create_feature_flag(default_team, self.user)
                    org_reports_with_flag = _send_all_org_usage_reports(dry_run=True)
                    org_report_with_flag = self.select_report_by_org_id(
                        str(default_team.organization.id), org_reports_with_flag
                    )
                    self.assertEqual(org_report_with_flag["feature_flag_count"], 1)

                    # Create session recording events (backdated)
                    _create_session_recording(
                        distinct_id="new_user1",
                        created_at=now() - relativedelta(days=2, minutes=2),
                        team=default_team,
                        session_id="session1_abcdef",
                    )
                    _create_session_recording(
                        distinct_id="new_user1",
                        created_at=now() - relativedelta(days=2, minutes=1),
                        team=default_team,
                        session_id="session1_abcdef",
                    )
                    _create_session_recording(
                        distinct_id="new_user2",
                        created_at=now() - relativedelta(days=2),
                        team=default_team,
                        session_id="session2_abcdef",
                    )

                    # Generate report and verify that 2 sessions are counted
                    org_reports_with_recordings = _send_all_org_usage_reports(dry_run=True)
                    org_report_with_recordings = self.select_report_by_org_id(
                        str(default_team.organization.id), org_reports_with_recordings
                    )
                    self.assertEqual(org_report_with_recordings["session_recording_count_in_month"], 2)

    return TestOrganizationUsageReport  # type: ignore


def create_person(distinct_id: str, team: Team) -> Person:
    return Person.objects.create(team=team, distinct_ids=[distinct_id])


def create_feature_flag(team: Team, user: User, **kwargs) -> FeatureFlag:  # type: ignore
    return FeatureFlag.objects.create(team=team, name="Beta feature", key="beta-feature", created_by=user, **kwargs)


def create_event_postgres(distinct_id: str, event: str, lib: str, created_at: datetime, team: Team) -> Event:
    return Event.objects.create(
        team=team,
        distinct_id=distinct_id,
        event=event,
        timestamp=created_at,
        created_at=created_at,
        properties={"$lib": lib},
    )


def create_session_recording_postgres(
    distinct_id: str, created_at: datetime, team: Team, session_id: str
) -> SessionRecordingEvent:
    return SessionRecordingEvent.objects.create(
        team=team,
        distinct_id=distinct_id,
        created_at=created_at,
        timestamp=created_at,
        session_id=session_id,
        snapshot_data={},
    )


class TestOrganizationUsageReport(factory_org_usage_report(create_person, create_event_postgres, create_session_recording_postgres, send_all_org_usage_reports, {"EE_AVAILABLE": False, "USE_TZ": False})):  # type: ignore
    pass
