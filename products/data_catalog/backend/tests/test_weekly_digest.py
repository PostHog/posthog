from datetime import timedelta
from typing import Never

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import OperationalError
from django.template.loader import get_template
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from temporalio.client import Schedule, ScheduleActionStartWorkflow

from posthog.constants import AvailableFeature
from posthog.email import inline_css
from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.organization_notification_lock import OrganizationMemberNotificationLock

from products.access_control.backend.models.access_control import AccessControl
from products.data_catalog.backend.facade.contracts import DigestRow, DigestSource
from products.data_catalog.backend.facade.enums import MetricStatus
from products.data_catalog.backend.logic.metrics import update_metric
from products.data_catalog.backend.logic.pending_review import PendingGroup, PendingKind, TeamPendingReview
from products.data_catalog.backend.models import Metric
from products.data_catalog.backend.temporal.schedule import create_data_catalog_weekly_digest_schedule
from products.data_catalog.backend.temporal.weekly_digest.activities import (
    _build_and_send_for_org,
    _get_org_batch_page,
    _run_digest_batch,
    _send_digest_for_user,
)
from products.data_catalog.backend.temporal.weekly_digest.email_context import (
    MAX_PROJECT_SECTIONS,
    app_url,
    build_project_section,
    build_subject,
    build_template_context,
    catalog_path,
    pending_rows,
)
from products.data_catalog.backend.temporal.weekly_digest.types import (
    DataCatalogWeeklyDigestInput,
    DigestBatchInput,
    DigestBatchResult,
    DigestOutcome,
    OrgBatchPageInput,
    OrgDigestCounts,
    ProjectDigest,
)
from products.data_catalog.backend.temporal.weekly_digest.workflows import DataCatalogWeeklyDigestWorkflow

_ACTIVITIES = "products.data_catalog.backend.temporal.weekly_digest.activities"
GMAIL_CLIP_BYTES = 102_000


def _review(team: Team, certifications: int = 3, new_certifications: int = 1) -> TeamPendingReview:
    groups = [
        PendingGroup(
            kind=PendingKind.CERTIFICATIONS,
            noun="certification",
            count=certifications,
            sample_names=["customer_facts"],
            new_count=new_certifications,
        ),
    ]
    return TeamPendingReview(team_id=team.id, team_name=team.name, groups=groups, total=certifications)


def _project(review: TeamPendingReview) -> ProjectDigest:
    return ProjectDigest(team_id=review.team_id, team_name=review.team_name, rows=pending_rows(review.groups))


def _pending_metrics(team_id: int, count: int, sample_names: list[str], team_name: str = "Acme") -> ProjectDigest:
    return _project(
        TeamPendingReview(
            team_id=team_id,
            team_name=team_name,
            groups=[PendingGroup(kind=PendingKind.METRICS, noun="metric", count=count, sample_names=sample_names)],
            total=count,
        )
    )


class TestEmailContext(SimpleTestCase):
    @parameterized.expand(
        [
            (1, 4, "1 new item to review in your data catalog"),
            (3, 4, "3 new items to review in your data catalog"),
            (0, 4, "4 items to review in your data catalog"),
        ]
    )
    def test_subject_leads_with_the_new_items(self, new_total: int, total: int, expected: str) -> None:
        assert build_subject(new_total, total) == expected

    def test_review_links_open_the_queue_filtered_to_proposed_items(self) -> None:
        assert app_url(7, catalog_path(PendingKind.RELATIONSHIPS)) == (
            f"{settings.SITE_URL}/project/7/data-catalog"
            "?tab=relationships&filter=proposed&utm_source=data_catalog_weekly_digest&utm_medium=email"
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

        section = build_project_section(_project(review))

        assert "tab=relationships" in section["review_url"]
        assert section["project_url"] == section["review_url"]
        assert section["rows"][0]["omitted_count"] == 0
        assert section["rows"][1]["omitted_count"] == 8

    def test_url_shaped_names_never_reach_the_email(self) -> None:
        project = _pending_metrics(
            team_id=7, count=3, sample_names=["revenue", "https://phishing.example"], team_name="www.phishing.example"
        )

        section = build_project_section(project)

        assert section["team_name"] == "Your project"
        assert section["rows"][0]["sample_names"] == ["revenue"]
        assert section["rows"][0]["omitted_count"] == 2

    def test_rendered_email_leaves_no_domain_shaped_name_linkable(self) -> None:
        project = _pending_metrics(
            team_id=7, count=1, sample_names=["posthog.login.attacker.com"], team_name="acme.attacker.com"
        )
        context = build_template_context(Organization(name="login.attacker.com"), [project])

        html_body = get_template("email/data_catalog_weekly_digest.html").render(context)

        assert "attacker.com" not in html_body
        assert html_body.count("attacker.\u200bcom") == 3

    def test_a_project_with_new_items_is_never_cut_by_the_project_cap(self) -> None:
        old_backlogs = [
            _pending_metrics(team_id=index, count=100, sample_names=[]) for index in range(MAX_PROJECT_SECTIONS)
        ]
        small_new = ProjectDigest(
            team_id=99,
            team_name="Small",
            rows=[DigestRow(noun="metric", count=1, new_count=1, sample_names=[], path="/data-catalog")],
        )

        context = build_template_context(Organization(name="Acme"), [*old_backlogs, small_new])

        assert context["project_sections"][0]["team_name"] == "Small"
        assert context["omitted_project_count"] == 1

    def test_the_largest_email_stays_under_the_size_gmail_clips_at(self) -> None:
        nouns = ["metric", "relationship", "certification", "certification suggestion", "model suggestion"]
        rows = [
            DigestRow(noun=noun, count=50, new_count=5, sample_names=["n" * 80] * 5, path="/data-catalog?tab=metrics")
            for noun in nouns
        ]
        projects = [
            ProjectDigest(team_id=index, team_name="p" * 60, rows=rows) for index in range(MAX_PROJECT_SECTIONS + 1)
        ]
        context = build_template_context(Organization(name="Acme"), projects)

        html_body = inline_css(get_template("email/data_catalog_weekly_digest.html").render(context))

        assert len(html_body.encode()) < GMAIL_CLIP_BYTES

    def test_lists_the_busiest_projects_and_counts_the_rest(self) -> None:
        counts = range(1, MAX_PROJECT_SECTIONS + 2)
        projects = [_pending_metrics(team_id=count, count=count, sample_names=[]) for count in counts]

        context = build_template_context(Organization(name="Acme"), projects)

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

    def _send(self, *, dry_run: bool = False, test: bool = False, new_certifications: int = 1) -> DigestOutcome:
        return _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            reviews={self.team.id: _review(self.team, new_certifications=new_certifications)},
            teams_by_id={self.team.id: self.team},
            date_suffix="2026-15",
            dry_run=dry_run,
            test=test,
        )

    def test_sends_with_default_notification_settings(self) -> None:
        outcome = self._send()

        assert outcome == DigestOutcome.SENT
        kwargs = self.mock_email_class.call_args.kwargs
        assert kwargs["subject"] == "1 new item to review in your data catalog"
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

    @parameterized.expand([(False, DigestOutcome.SKIPPED_NOTHING_NEW), (True, DigestOutcome.SENT)])
    def test_a_backlog_with_nothing_new_sends_only_in_test_mode(self, test: bool, expected: DigestOutcome) -> None:
        assert self._send(test=test, new_certifications=0) == expected

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

    @parameterized.expand([("hidden", {"payroll"}, 0), ("readable", set(), 1)])
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_a_new_metric_counts_only_for_people_who_can_read_its_tables(
        self, _name: str, denied_tables: set[str], expected_sent: int, create_database: MagicMock
    ) -> None:
        create_database.return_value = MagicMock(_denied_tables=denied_tables)
        Metric.objects.unscoped().filter(team=self.team).update(created_at=timezone.now() - timedelta(days=8))
        Metric.objects.unscoped().create(
            team=self.team, name="median_salary_by_level", description="d", referenced_table_names=["payroll"]
        )

        counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == expected_sent
        if expected_sent:
            (row,) = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"][0]["rows"]
            assert row["new_count"] == 1

    @parameterized.expand([(1, 1), (8, 0)])
    def test_sends_only_when_an_item_arrived_in_the_last_week(self, days_old: int, expected_sent: int) -> None:
        Metric.objects.unscoped().filter(team=self.team).update(created_at=timezone.now() - timedelta(days=days_old))

        counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == expected_sent
        assert counts.skipped_nothing_new == 1 - expected_sent

    def _model_suggestion_source(self) -> DigestSource:
        return DigestSource(
            name="suggestions",
            rows=lambda team, user, new_since: [
                DigestRow(
                    noun="model suggestion", count=2, new_count=1, sample_names=["orders"], path="/models?tab=models"
                )
            ],
            teams_with_rows=lambda teams: {self.team.id},
        )

    def test_a_project_with_only_suggestions_gets_the_email(self) -> None:
        Metric.objects.unscoped().filter(team=self.team).delete()

        with patch(f"{_ACTIVITIES}.load_digest_sources", return_value=(self._model_suggestion_source(),)):
            counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == 1
        (row,) = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"][0]["rows"]
        assert row["review_url"] == (
            f"{settings.SITE_URL}/project/{self.team.id}/models"
            "?tab=models&utm_source=data_catalog_weekly_digest&utm_medium=email"
        )

    def test_someone_without_catalog_access_still_gets_the_suggestions_they_can_act_on(self) -> None:
        AccessControl.objects.create(team=self.team, resource="data_catalog", access_level="none")
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with patch(f"{_ACTIVITIES}.load_digest_sources", return_value=(self._model_suggestion_source(),)):
            counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == 1
        sections = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"]
        assert [row["noun"] for row in sections[0]["rows"]] == ["model suggestion"]

    def test_a_metric_that_returns_to_review_this_week_counts_as_new(self) -> None:
        Metric.objects.unscoped().filter(team=self.team).update(
            created_at=timezone.now() - timedelta(days=30), status=MetricStatus.APPROVED
        )
        metric = Metric.objects.unscoped().get(team=self.team)

        update_metric(metric, team=self.team, user=self.user, description="Counts a different thing now")
        counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == 1

    def test_a_failing_catalog_read_still_sends_the_other_rows(self) -> None:
        with (
            patch(f"{_ACTIVITIES}.load_digest_sources", return_value=(self._model_suggestion_source(),)),
            patch(f"{_ACTIVITIES}.groups_visible_to", side_effect=RuntimeError("database build failed")),
        ):
            counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == 1
        sections = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"]
        assert [row["noun"] for row in sections[0]["rows"]] == ["model suggestion"]

    def test_a_source_module_that_fails_to_import_keeps_the_catalog_email(self) -> None:
        with patch(f"{_ACTIVITIES}.load_digest_sources", side_effect=ImportError("broken source module")):
            counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == 1

    def test_the_batch_counts_new_items_from_the_cutoff_the_workflow_passes(self) -> None:
        Metric.objects.unscoped().filter(team=self.team).update(created_at=timezone.now() - timedelta(days=3))

        totals = _run_digest_batch(
            DigestBatchInput(
                org_ids=[str(self.organization.id)], new_since=(timezone.now() - timedelta(days=1)).isoformat()
            )
        )

        assert (totals.emails_sent, totals.emails_skipped_nothing_new) == (0, 1)

    @parameterized.expand([("rows", True, False), ("teams_with_rows", False, True)])
    def test_a_failing_source_keeps_the_catalog_rows(self, _name: str, rows_fail: bool, teams_fail: bool) -> None:
        def fail(*args: object) -> Never:
            raise RuntimeError("source down")

        def no_rows(*args: object) -> list[DigestRow]:
            return []

        def this_team(*args: object) -> set[int]:
            return {self.team.id}

        source = DigestSource(
            name="suggestions",
            rows=fail if rows_fail else no_rows,
            teams_with_rows=fail if teams_fail else this_team,
        )

        with patch(f"{_ACTIVITIES}.load_digest_sources", return_value=(source,)):
            counts = _build_and_send_for_org(str(self.organization.id))

        assert counts.sent == 1
        sections = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"]
        assert [row["noun"] for row in sections[0]["rows"]] == ["metric"]

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


@pytest.mark.parametrize(
    "orgs_processed,orgs_failed,exceeded",
    [
        (0, 2, False),
        (18, 2, False),
        (10, 10, True),
        (0, 25, True),
    ],
)
def test_the_failure_threshold_needs_enough_attempted_orgs(
    orgs_processed: int, orgs_failed: int, exceeded: bool
) -> None:
    totals = DigestBatchResult(orgs_processed=orgs_processed, orgs_failed=orgs_failed, orgs_skipped=75_000)
    assert DataCatalogWeeklyDigestInput().exceeds_failure_threshold(totals) is exceeded


@pytest.mark.parametrize(
    "side_effect,orgs_processed,orgs_failed",
    [
        ([OperationalError("connection closed"), OrgDigestCounts(sent=1)], 1, 0),
        ([OperationalError("connection closed"), OperationalError("connection closed")], 0, 1),
        ([ValueError("bug")], 0, 1),
    ],
)
def test_a_dropped_database_connection_is_retried_once(
    side_effect: list, orgs_processed: int, orgs_failed: int
) -> None:
    with (
        patch(f"{_ACTIVITIES}.close_old_connections"),
        patch(f"{_ACTIVITIES}.capture_exception"),
        patch(f"{_ACTIVITIES}._build_and_send_for_org", side_effect=side_effect),
    ):
        totals = _run_digest_batch(DigestBatchInput(org_ids=["org"]))

    assert (totals.orgs_processed, totals.orgs_failed) == (orgs_processed, orgs_failed)
