from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from temporalio.client import WorkflowExecutionStatus

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Project, Team, User
from posthog.temporal.ai_observability.run_session_evaluation import AI_EVENTS_RETENTION_DAYS

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.api.evaluation_backfills import BACKFILL_RETENTION_MARGIN
from products.ai_observability.backend.models.evaluation_backfill import EvaluationBackfill, EvaluationBackfillStatus
from products.ai_observability.backend.models.evaluations import Evaluation

API_MODULE = "products.ai_observability.backend.api.evaluation_backfills"


def _other_team() -> Team:
    org = Organization.objects.create(name="other")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    return Team.objects.create(id=project.id, project=project, organization=org)


def _evaluation(team: Team, conditions: list[dict] | None = None) -> Evaluation:
    return Evaluation.objects.create(
        team=team,
        name="e",
        evaluation_type="hog",
        enabled=True,
        evaluation_config={"source": "return true"},
        output_type="boolean",
        output_config={},
        conditions=conditions
        if conditions is not None
        else [{"id": "c1", "properties": [], "rollout_percentage": 100}],
    )


def _body(**overrides) -> dict:
    now = timezone.now()
    return {
        "window_start": (now - timedelta(days=7)).isoformat(),
        "window_end": now.isoformat(),
        **overrides,
    }


def _temporal_client(workflow_status: WorkflowExecutionStatus | None = WorkflowExecutionStatus.RUNNING) -> MagicMock:
    client = MagicMock()
    client.start_workflow = AsyncMock()
    handle = MagicMock(
        cancel=AsyncMock(),
        describe=AsyncMock(return_value=MagicMock(status=workflow_status)),
    )
    client.get_workflow_handle = MagicMock(return_value=handle)
    return client


class TestEvaluationBackfillsApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.evaluation = _evaluation(self.team, [{"id": "c1", "properties": [], "rollout_percentage": 50}])
        self.url = f"/api/projects/{self.team.id}/evaluations/{self.evaluation.id}/backfills"

    def _running_backfill(self, evaluation: Evaluation | None = None) -> EvaluationBackfill:
        now = timezone.now()
        evaluation = evaluation or self.evaluation
        return EvaluationBackfill.objects.unscoped().create(
            evaluation=evaluation,
            team=evaluation.team,
            window_start=now - timedelta(days=1),
            window_end=now,
            target="generation",
            conditions=[],
            total_count=1,
        )

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=42)
    def test_estimate_counts_without_creating_a_row(self, _count):
        response = self.client.post(f"{self.url}/estimate/", _body(), format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["total_units"] == 42
        assert response.json()["unit"] == "generation"
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=42)
    @patch(f"{API_MODULE}.sync_connect")
    def test_create_freezes_conditions_and_starts_workflow(self, connect, _count):
        connect.return_value = _temporal_client()

        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["total_count"] == 42
        assert body["status"] == EvaluationBackfillStatus.RUNNING
        assert body["conditions"] == [{"properties": [], "rollout_percentage": 50}]
        assert body["rerun_existing"] is False

        row = EvaluationBackfill.objects.unscoped().get(pk=body["id"])
        assert row.team_id == self.team.id
        assert row.target == "generation"

        call = connect.return_value.start_workflow.call_args
        assert call.args[0] == "llma-evaluation-backfill"
        assert call.args[1].backfill_id == str(row.id)
        assert call.args[1].team_id == self.team.id
        assert call.kwargs["id"] == f"llma-evaluation-backfill-{row.id}"
        assert call.kwargs["task_queue"] == settings.LLMA_TASK_QUEUE

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=7)
    @patch(f"{API_MODULE}.sync_connect")
    def test_create_uses_submitted_conditions_and_rerun_flag(self, connect, _count):
        connect.return_value = _temporal_client()
        conditions = [
            {"id": "sent", "properties": [{"key": "x", "value": "y", "type": "event"}], "rollout_percentage": 10}
        ]

        response = self.client.post(f"{self.url}/", _body(conditions=conditions, rerun_existing=True), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["rerun_existing"] is True
        assert body["conditions"] == [
            {"properties": [{"key": "x", "value": "y", "type": "event"}], "rollout_percentage": 10}
        ]

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=7)
    @patch(f"{API_MODULE}.sync_connect")
    def test_create_rejects_second_active_backfill(self, connect, _count):
        connect.return_value = _temporal_client()
        self._running_backfill()

        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already has a running backfill" in response.json()["detail"]

    @parameterized.expand(
        [
            ("workflow_completed", WorkflowExecutionStatus.COMPLETED),
            ("workflow_failed", WorkflowExecutionStatus.FAILED),
            ("workflow_gone", None),
        ]
    )
    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=7)
    @patch(f"{API_MODULE}.sync_connect")
    def test_create_releases_a_row_whose_workflow_is_no_longer_running(self, _case, workflow_status, connect, _count):
        connect.return_value = _temporal_client(workflow_status)
        stale = self._running_backfill()

        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        stale.refresh_from_db()
        assert stale.status == EvaluationBackfillStatus.CANCELLED
        assert stale.finished_at is not None

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=7)
    @patch(f"{API_MODULE}.sync_connect", side_effect=RuntimeError("temporal down"))
    def test_create_keeps_refusing_when_temporal_cannot_be_reached(self, _connect, _count):
        stale = self._running_backfill()

        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already has a running backfill" in response.json()["detail"]
        stale.refresh_from_db()
        assert stale.status == EvaluationBackfillStatus.RUNNING

    @parameterized.expand(["start_after_end", "entirely_in_future"])
    def test_create_rejects_bad_windows(self, case):
        now = timezone.now()
        windows = {
            "start_after_end": (now, now - timedelta(days=1)),
            "entirely_in_future": (now + timedelta(days=1), now + timedelta(days=2)),
        }
        window_start, window_end = windows[case]

        response = self.client.post(
            f"{self.url}/",
            {"window_start": window_start.isoformat(), "window_end": window_end.isoformat()},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @parameterized.expand(["evaluation_has_no_conditions", "explicit_empty_list"])
    def test_rejects_a_backfill_with_no_condition_sets(self, case):
        body = _body()
        if case == "evaluation_has_no_conditions":
            self.evaluation.conditions = []
            self.evaluation.save()
        else:
            body["conditions"] = []

        for path in (f"{self.url}/", f"{self.url}/estimate/"):
            response = self.client.post(path, body, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST, (path, response.json())
            assert "at least one condition set" in response.json()["detail"]
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=3)
    @patch(f"{API_MODULE}.sync_connect")
    def test_clamps_a_window_wider_than_retention(self, connect, _count):
        connect.return_value = _temporal_client()
        now = timezone.now()
        body = _body(
            window_start=(now - timedelta(days=90)).isoformat(),
            window_end=(now + timedelta(days=1)).isoformat(),
        )

        estimate = self.client.post(f"{self.url}/estimate/", body, format="json")
        assert estimate.status_code == status.HTTP_200_OK, estimate.json()
        assert abs(datetime.fromisoformat(estimate.json()["window_end"]) - now) < timedelta(seconds=5)
        expected_start = now - timedelta(days=AI_EVENTS_RETENTION_DAYS)
        assert abs(datetime.fromisoformat(estimate.json()["window_start"]) - expected_start) < timedelta(seconds=5)

        created = self.client.post(f"{self.url}/", body, format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        row = EvaluationBackfill.objects.unscoped().get(pk=created.json()["id"])
        assert abs(row.window_end - now) < timedelta(seconds=5)
        assert abs(row.window_start - expected_start) < timedelta(seconds=5)

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=3)
    @patch(f"{API_MODULE}.sync_connect")
    def test_clamps_the_window_to_the_projects_drop_threshold(self, connect, _count):
        connect.return_value = _temporal_client()
        self.team.drop_events_older_than = timedelta(days=3)
        self.team.save()
        now = timezone.now()
        body = _body(window_start=(now - timedelta(days=20)).isoformat())

        created = self.client.post(f"{self.url}/", body, format="json")

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        row = EvaluationBackfill.objects.unscoped().get(pk=created.json()["id"])
        # The margin buys the walk time to reach the oldest units before their verdicts age out.
        expected = now - timedelta(days=3) + BACKFILL_RETENTION_MARGIN
        assert abs(row.window_start - expected) < timedelta(seconds=5)

    @parameterized.expand(
        [
            ("days", timedelta(days=3), "3 days"),
            ("hours", timedelta(hours=6), "6 hours"),
            ("fractional_days", timedelta(days=1, hours=12), "about 1.5 days"),
            # The margin alone leaves no window, so a short threshold is refused outright.
            ("threshold_under_the_margin", timedelta(hours=12), "12 hours"),
        ]
    )
    def test_rejects_a_window_entirely_older_than_the_drop_threshold(self, _case, threshold, label):
        self.team.drop_events_older_than = threshold
        self.team.save()
        now = timezone.now()
        body = _body(
            window_start=(now - timedelta(days=10)).isoformat(),
            window_end=(now - timedelta(days=9)).isoformat(),
        )

        response = self.client.post(f"{self.url}/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == (
            f"Your project drops events older than {label}, so backfills can only reach back that far."
        )
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @parameterized.expand(["create", "estimate"])
    def test_a_disabled_evaluation_cannot_be_backfilled(self, case):
        self.evaluation.enabled = False
        self.evaluation.save()
        path = f"{self.url}/" if case == "create" else f"{self.url}/estimate/"

        response = self.client.post(path, _body(), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == "Enable the evaluation before backfilling it."
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @parameterized.expand(["list", "estimate"])
    def test_another_teams_evaluation_is_not_addressable(self, case):
        other_evaluation = _evaluation(_other_team())
        url = f"/api/projects/{self.team.id}/evaluations/{other_evaluation.id}/backfills"

        if case == "list":
            response = self.client.get(f"{url}/")
        else:
            response = self.client.post(f"{url}/estimate/", _body(), format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=0)
    def test_create_rejects_empty_window(self, _count):
        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No generations in this range" in response.json()["detail"]
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=5)
    @patch(f"{API_MODULE}.sync_connect", side_effect=RuntimeError("temporal down"))
    def test_create_rolls_back_row_when_workflow_start_fails(self, _connect, _count):
        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code >= 500
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @patch(f"{API_MODULE}.sync_connect")
    def test_cancel_marks_terminal_and_is_idempotent(self, connect):
        connect.return_value = _temporal_client()
        backfill = self._running_backfill()

        first = self.client.post(f"{self.url}/{backfill.id}/cancel/", format="json")
        assert first.status_code == status.HTTP_200_OK, first.json()
        assert first.json()["status"] == EvaluationBackfillStatus.CANCELLED
        assert first.json()["finished_at"] is not None
        connect.return_value.get_workflow_handle.assert_called_once_with(f"llma-evaluation-backfill-{backfill.id}")
        connect.return_value.get_workflow_handle.return_value.cancel.assert_awaited_once()

        second = self.client.post(f"{self.url}/{backfill.id}/cancel/", format="json")
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["status"] == EvaluationBackfillStatus.CANCELLED
        assert second.json()["finished_at"] == first.json()["finished_at"]

    def test_list_is_scoped_to_evaluation_and_team(self):
        mine = self._running_backfill()
        self._running_backfill(_evaluation(_other_team()))

        response = self.client.get(f"{self.url}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [row["id"] for row in response.json()["results"]] == [str(mine.id)]


class TestEvaluationBackfillsAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.evaluation = _evaluation(self.team)
        self.url = f"/api/projects/{self.team.id}/evaluations/{self.evaluation.id}/backfills"
        viewer = User.objects.create_and_join(self.organization, "backfill-viewer@posthog.com", "testtest")
        self.viewer_membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            resource_id=None,
            access_level="viewer",
            organization_member=self.viewer_membership,
        )
        self.client.force_login(viewer)

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=4)
    def test_viewer_can_estimate_but_cannot_create(self, _count):
        body = _body()

        estimate = self.client.post(f"{self.url}/estimate/", body, format="json")
        assert estimate.status_code == status.HTTP_200_OK, estimate.json()
        assert estimate.json()["total_units"] == 4

        created = self.client.post(f"{self.url}/", body, format="json")
        assert created.status_code == status.HTTP_403_FORBIDDEN, created.json()
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=4)
    @patch(f"{API_MODULE}.sync_connect")
    def test_editor_on_this_evaluation_can_create_despite_being_a_viewer_on_the_resource(self, connect, _count):
        connect.return_value = _temporal_client()
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            resource_id=str(self.evaluation.id),
            access_level="editor",
            organization_member=self.viewer_membership,
        )
        body = _body()

        created = self.client.post(f"{self.url}/", body, format="json")

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        assert EvaluationBackfill.objects.unscoped().count() == 1
