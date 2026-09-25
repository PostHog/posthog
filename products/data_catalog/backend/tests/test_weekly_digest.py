from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from temporalio.client import Schedule, ScheduleActionStartWorkflow

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.organization_notification_lock import OrganizationMemberNotificationLock

from products.access_control.backend.models.access_control import AccessControl
from products.data_catalog.backend.logic.pending_review import PendingGroup, PendingKind, TeamPendingReview
from products.data_catalog.backend.models import Metric
from products.data_catalog.backend.temporal.schedule import create_data_catalog_weekly_digest_schedule
from products.data_catalog.backend.temporal.weekly_digest.activities import (
    _build_and_send_for_org,
    _get_org_batch_page,
    _send_digest_for_user,
)
from products.data_catalog.backend.temporal.weekly_digest.email_context import (
    MAX_PROJECT_SECTIONS,
    build_project_section,
    build_subject,
    build_template_context,
    catalog_url,
)
from products.data_catalog.backend.temporal.weekly_digest.types import (
    DataCatalogWeeklyDigestInput,
    DigestOutcome,
    OrgBatchPageInput,
)
from products.data_catalog.backend.temporal.weekly_digest.workflows import DataCatalogWeeklyDigestWorkflow

_ACTIVITIES = "products.data_catalog.backend.temporal.weekly_digest.activities"


def _review(team: Team, metrics: int = 2, certifications: int = 1) -> TeamPendingReview:
    groups = [
        PendingGroup(kind=PendingKind.METRICS, noun="metric", count=metrics, sample_names=["revenue"]),
        PendingGroup(
            kind=PendingKind.CERTIFICATIONS,
            noun="certification",
            count=certifications,
            sample_names=["customer_facts"],
        ),
    ]
    return TeamPendingReview(
        team_id=team.id,
        team_name=team.name,
        groups=groups,
        total=metrics + certifications,
    )


def _pending_metrics(team_id: int, count: int, sample_names: list[str], team_name: str = "Acme") -> TeamPendingReview:
    return TeamPendingReview(
        team_id=team_id,
        team_name=team_name,
        groups=[PendingGroup(kind=PendingKind.METRICS, noun="metric", count=count, sample_names=sample_names)],
        total=count,
    )


class TestEmailContext(SimpleTestCase):
    @parameterized.expand(
        [(1, "1 item awaiting review in your data catalog"), (4, "4 items awaiting review in your data catalog")]
    )
    def test_subject_counts_items(self, total: int, expected: str) -> None:
        assert build_subject(total) == expected

    def test_review_links_open_the_tab_that_holds_the_queue(self) -> None:
        assert catalog_url(7, PendingKind.RELATIONSHIPS) == (
            f"{settings.SITE_URL}/project/7/data-catalog"
            "?tab=relationships&utm_source=data_catalog_weekly_digest&utm_medium=email"
        )

    def test_primary_button_opens_the_busiest_queue(self) -> None:
        review = TeamPendingReview(
            team_id=7,
            team_name="Acme",
            groups=[
                PendingGroup(kind=PendingKind.METRICS, noun="metric", count=1, sample_names=["revenue"]),
                PendingGroup(kind=PendingKind.RELATIONSHIPS, noun="relationship", count=9, sample_names=["a to b"]),
            ],
            total=10,
        )

        section = build_project_section(review)

        assert "tab=relationships" in section["review_url"]
        assert section["rows"][0]["omitted_count"] == 0
        assert section["rows"][1]["omitted_count"] == 8

    def test_url_shaped_names_never_reach_the_email(self) -> None:
        review = _pending_metrics(
            team_id=7, count=3, sample_names=["revenue", "https://phishing.example"], team_name="www.phishing.example"
        )

        section = build_project_section(review)

        assert section["team_name"] == "Your project"
        assert section["rows"][0]["sample_names"] == ["revenue"]
        assert section["rows"][0]["omitted_count"] == 2

    def test_lists_the_busiest_projects_and_counts_the_rest(self) -> None:
        counts = range(1, MAX_PROJECT_SECTIONS + 2)
        reviews = [_pending_metrics(team_id=count, count=count, sample_names=[]) for count in counts]

        context = build_template_context(Organization(name="Acme"), reviews)

        assert [section["total"] for section in context["project_sections"]] == sorted(counts, reverse=True)[
            :MAX_PROJECT_SECTIONS
        ]
        assert context["omitted_project_count"] == 1
        assert context["total"] == sum(counts)


class TestSendDigestForUser(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.is_email_patcher = patch(f"{_ACTIVITIES}.is_email_available", return_value=True)
        self.is_email_patcher.start()
        self.email_class_patcher = patch(f"{_ACTIVITIES}.EmailMessage")
        self.mock_email_class = self.email_class_patcher.start()
        self.mock_message = MagicMock()
        self.mock_email_class.return_value = self.mock_message

    def tearDown(self) -> None:
        self.is_email_patcher.stop()
        self.email_class_patcher.stop()
        super().tearDown()

    def _send(self, *, dry_run: bool = False, test: bool = False) -> DigestOutcome:
        return _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            reviews={self.team.id: _review(self.team)},
            teams_by_id={self.team.id: self.team},
            date_suffix="2026-15",
            dry_run=dry_run,
            test=test,
        )

    def test_sends_with_default_notification_settings(self) -> None:
        outcome = self._send()

        assert outcome == DigestOutcome.SENT
        kwargs = self.mock_email_class.call_args.kwargs
        assert kwargs["subject"] == "3 items awaiting review in your data catalog"
        assert kwargs["template_context"]["total"] == 3
        self.mock_message.add_user_recipient.assert_called_once_with(self.user)
        self.mock_message.send.assert_called_once()

    def test_skips_when_the_user_turned_the_digest_off(self) -> None:
        self.user.partial_notification_settings = {"data_catalog_weekly_digest": False}
        self.user.save()

        assert self._send() == DigestOutcome.SKIPPED_OPTOUT
        self.mock_email_class.assert_not_called()

    def test_sends_anyway_in_test_mode_and_never_dedupes(self) -> None:
        self.user.partial_notification_settings = {"data_catalog_weekly_digest": False}
        self.user.save()

        assert self._send(test=True) == DigestOutcome.SENT
        assert "_test_" in self.mock_email_class.call_args.kwargs["campaign_key"]

    def test_campaign_key_is_stable_within_a_week(self) -> None:
        self._send()
        first = self.mock_email_class.call_args.kwargs["campaign_key"]
        self._send()
        second = self.mock_email_class.call_args.kwargs["campaign_key"]

        assert first == second
        assert str(self.user.uuid) in first

    def test_dry_run_sends_nothing(self) -> None:
        assert self._send(dry_run=True) == DigestOutcome.DRY_RUN
        self.mock_email_class.assert_not_called()

    @parameterized.expand([("project", True), ("data_catalog", False)])
    def test_skips_a_project_the_user_cannot_read(self, denied_resource: str, scoped_to_team: bool) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource=denied_resource,
            resource_id=str(self.team.id) if scoped_to_team else None,
            access_level="none",
        )
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        assert self._send() == DigestOutcome.SKIPPED_NO_DATA
        self.mock_email_class.assert_not_called()


class TestBuildAndSendForOrg(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.is_email_patcher = patch(f"{_ACTIVITIES}.is_email_available", return_value=True)
        self.is_email_patcher.start()
        self.email_class_patcher = patch(f"{_ACTIVITIES}.EmailMessage")
        self.mock_email_class = self.email_class_patcher.start()
        self.mock_email_class.return_value = MagicMock()
        self.close_conn_patcher = patch(f"{_ACTIVITIES}.close_old_connections")
        self.close_conn_patcher.start()
        self.flag_patcher = patch(f"{_ACTIVITIES}._is_user_flag_enabled", return_value=True)
        self.flag_patcher.start()
        Metric.objects.unscoped().create(team=self.team, name="proposed_one", description="d")

    def tearDown(self) -> None:
        self.flag_patcher.stop()
        self.close_conn_patcher.stop()
        self.is_email_patcher.stop()
        self.email_class_patcher.stop()
        super().tearDown()

    @parameterized.expand([(True, 1), (False, 0)])
    def test_only_active_accounts_receive_the_digest(self, is_active: bool, expected_sent: int) -> None:
        self.user.is_active = is_active
        self.user.save()

        counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == expected_sent

    @parameterized.expand(
        [
            ("open", {}, 1),
            ("never_deactivated", {"is_active": None}, 1),
            ("deactivated", {"is_active": False}, 0),
            ("pending_deletion", {"is_pending_deletion": True}, 0),
        ]
    )
    def test_an_organization_the_app_blocks_receives_nothing(self, _name, fields, expected_sent) -> None:
        for field, value in fields.items():
            setattr(self.organization, field, value)
        self.organization.save()

        counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == expected_sent

    @parameterized.expand([("this_org", 0), ("other_org", 1)])
    def test_only_the_sending_organization_locks_its_own_digest(self, locking_org: str, expected_sent: int) -> None:
        other_org = Organization.objects.create(name="Other")
        other_membership = OrganizationMembership.objects.create(organization=other_org, user=self.user)
        lock_membership = self.organization_membership if locking_org == "this_org" else other_membership
        OrganizationMemberNotificationLock.objects.create(
            organization=lock_membership.organization,
            organization_membership=lock_membership,
            setting="data_catalog_weekly_digest",
            locked_value=False,
        )

        counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == expected_sent


class TestOrgBatchPage(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.is_email_patcher = patch(f"{_ACTIVITIES}.is_email_available", return_value=True)
        self.is_email_patcher.start()
        self.close_conn_patcher = patch(f"{_ACTIVITIES}.close_old_connections")
        self.close_conn_patcher.start()
        self.user.last_login = timezone.now()
        self.user.save()

    def tearDown(self) -> None:
        self.close_conn_patcher.stop()
        self.is_email_patcher.stop()
        super().tearDown()

    def _page(self, org_ids: list[str] | None) -> list[str]:
        result = _get_org_batch_page(OrgBatchPageInput(workflow_input=DataCatalogWeeklyDigestInput(org_ids=org_ids)))
        return [org_id for batch in result.batches for org_id in batch]

    def test_an_empty_target_list_selects_no_organizations(self) -> None:
        assert self._page([]) == []

    def test_no_target_list_discovers_active_organizations(self) -> None:
        assert str(self.organization.id) in self._page(None)


# The workflow is registered on WEEKLY_DIGEST_TASK_QUEUE by the worker bootstrap, but the schedule
# names its queue in a different file. If the two drift the digest fires into a queue nobody polls,
# and nothing surfaces it for a week, because the digest runs once a week. The schedule is also
# the one caller that must send for real, since dry_run defaults to True as a manual-run fail-safe.
@pytest.mark.asyncio
@override_settings(WEEKLY_DIGEST_TASK_QUEUE="weekly-digest-task-queue-under-test")
async def test_the_registered_schedule_is_live_on_the_weekly_digest_queue() -> None:
    captured: list[Schedule] = []
    schedule_module = "products.data_catalog.backend.temporal.schedule"

    with (
        mock.patch(f"{schedule_module}.a_schedule_exists", new=mock.AsyncMock(return_value=False)),
        mock.patch(
            f"{schedule_module}.a_create_schedule",
            new=mock.AsyncMock(side_effect=lambda client, schedule_id, schedule, **kwargs: captured.append(schedule)),
        ),
    ):
        await create_data_catalog_weekly_digest_schedule(mock.MagicMock())

    action = captured[0].action
    assert isinstance(action, ScheduleActionStartWorkflow)
    assert action.task_queue == settings.WEEKLY_DIGEST_TASK_QUEUE
    assert action.args == [DataCatalogWeeklyDigestInput(dry_run=False)]
    # Overlap defaults to SKIP, so an unbounded run would drop every later Tuesday for good.
    assert action.execution_timeout is not None
    assert action.execution_timeout < timedelta(days=7)


def test_an_inputless_manual_run_does_not_send() -> None:
    assert DataCatalogWeeklyDigestWorkflow.parse_inputs([]).dry_run is True


def test_a_mistyped_scope_key_fails_instead_of_widening_the_run() -> None:
    with pytest.raises(TypeError):
        DataCatalogWeeklyDigestWorkflow.parse_inputs(['{"org_idz": ["abc"], "dry_run": false}'])

    parsed = DataCatalogWeeklyDigestWorkflow.parse_inputs(['{"org_ids": ["abc"], "dry_run": false}'])
    assert parsed.org_ids == ["abc"]
    assert parsed.dry_run is False


# Pushgateway deletes every gauge already pushed under the digest's job name. A manual run that
# published would stand in for the weekly result and advance the last-run timestamp, so a staleness
# alert would read healthy through a week that sent nothing.
@pytest.mark.parametrize(
    "workflow_input,publishes",
    [
        (DataCatalogWeeklyDigestInput(dry_run=False), True),
        (DataCatalogWeeklyDigestInput(), False),
        (DataCatalogWeeklyDigestInput(dry_run=False, org_ids=["abc"]), False),
    ],
)
def test_only_the_full_real_run_publishes_metrics(
    workflow_input: DataCatalogWeeklyDigestInput, publishes: bool
) -> None:
    assert workflow_input.publishes_metrics is publishes
