from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Project, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.rate_limit import AIObservabilityBackfillCreateThrottle, AIObservabilityBackfillEstimateThrottle
from posthog.temporal.ai_observability.run_session_evaluation import AI_EVENTS_RETENTION_DAYS

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.api.evaluation_backfills import BACKFILL_RETENTION_MARGIN, BACKFILL_START_GRACE
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


def _throttle_request(user: User, personal_api_key: str | None = None) -> Request:
    headers = {"HTTP_AUTHORIZATION": f"Bearer {personal_api_key}"} if personal_api_key else {}
    # ty resolves the DRF Request constructor to its wrapped HttpRequest type; the cast restores it.
    request = cast(Request, Request(APIRequestFactory().post("/", **headers)))
    # Resolve the authenticator first. DRF resets `user` to anonymous when it finds none, which
    # would discard a user assigned before that.
    assert request.successful_authenticator is None
    request.user = user
    return request


def _temporal_client(
    workflow_status: WorkflowExecutionStatus | None = WorkflowExecutionStatus.RUNNING,
    describe_error: Exception | None = None,
) -> MagicMock:
    client = MagicMock()
    client.start_workflow = AsyncMock()
    handle = MagicMock(
        cancel=AsyncMock(),
        describe=AsyncMock(return_value=MagicMock(status=workflow_status), side_effect=describe_error),
    )
    client.get_workflow_handle = MagicMock(return_value=handle)
    return client


def _workflow_not_found() -> RPCError:
    return RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")


class TestEvaluationBackfillsApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.evaluation = _evaluation(self.team, [{"id": "c1", "properties": [], "rollout_percentage": 50}])
        self.url = f"/api/projects/{self.team.id}/evaluations/{self.evaluation.id}/backfills"

    def _running_backfill(
        self, evaluation: Evaluation | None = None, *, age: timedelta | None = None
    ) -> EvaluationBackfill:
        now = timezone.now()
        evaluation = evaluation or self.evaluation
        backfill = EvaluationBackfill.objects.unscoped().create(
            evaluation=evaluation,
            team=evaluation.team,
            window_start=now - timedelta(days=1),
            window_end=now,
            target="generation",
            conditions=[],
            total_count=1,
        )
        if age is not None:
            # created_at is auto_now_add, so ageing the row past BACKFILL_START_GRACE takes an update.
            EvaluationBackfill.objects.unscoped().filter(pk=backfill.pk).update(created_at=now - age)
            backfill.refresh_from_db()
        return backfill

    def _stale_backfill(self, evaluation: Evaluation | None = None) -> EvaluationBackfill:
        return self._running_backfill(evaluation, age=BACKFILL_START_GRACE + timedelta(minutes=1))

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

    @parameterized.expand(
        [
            ("workflow_running", WorkflowExecutionStatus.RUNNING, None),
            # A concurrent create that has not reached start_workflow yet leaves nothing to
            # describe, and its row must survive the probe rather than be treated as stale.
            ("workflow_not_started_yet", None, None),
            ("workflow_unknown_to_temporal", None, _workflow_not_found()),
        ]
    )
    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=7)
    @patch(f"{API_MODULE}.sync_connect")
    def test_create_rejects_a_second_backfill_while_a_recent_row_is_active(
        self, _case, workflow_status, describe_error, connect, _count
    ):
        connect.return_value = _temporal_client(workflow_status, describe_error)
        active = self._running_backfill()

        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already has a running backfill" in response.json()["detail"]
        active.refresh_from_db()
        assert active.status == EvaluationBackfillStatus.RUNNING

    @parameterized.expand(
        [
            ("workflow_completed", WorkflowExecutionStatus.COMPLETED, None),
            ("workflow_failed", WorkflowExecutionStatus.FAILED, None),
            ("workflow_gone", None, None),
            ("workflow_unknown_to_temporal", None, _workflow_not_found()),
        ]
    )
    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=7)
    @patch(f"{API_MODULE}.sync_connect")
    def test_create_releases_an_old_row_whose_workflow_is_no_longer_running(
        self, _case, workflow_status, describe_error, connect, _count
    ):
        connect.return_value = _temporal_client(workflow_status, describe_error)
        stale = self._stale_backfill()

        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        stale.refresh_from_db()
        assert stale.status == EvaluationBackfillStatus.CANCELLED
        assert stale.finished_at is not None

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=7)
    @patch(f"{API_MODULE}.sync_connect")
    def test_create_refuses_when_an_old_rows_workflow_still_runs(self, connect, _count):
        connect.return_value = _temporal_client(WorkflowExecutionStatus.RUNNING)
        active = self._stale_backfill()

        response = self.client.post(f"{self.url}/", _body(), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "already has a running backfill" in response.json()["detail"]
        active.refresh_from_db()
        assert active.status == EvaluationBackfillStatus.RUNNING

    @patch(f"{API_MODULE}.sync_connect")
    def test_list_releases_an_old_row_whose_workflow_is_gone(self, connect):
        connect.return_value = _temporal_client(None)
        stale = self._stale_backfill()

        response = self.client.get(f"{self.url}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"][0]["status"] == EvaluationBackfillStatus.CANCELLED
        stale.refresh_from_db()
        assert stale.status == EvaluationBackfillStatus.CANCELLED

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=7)
    @patch(f"{API_MODULE}.sync_connect", side_effect=RuntimeError("temporal down"))
    def test_create_keeps_refusing_when_temporal_cannot_be_reached(self, _connect, _count):
        stale = self._stale_backfill()

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
            # Past the margin the message has to quote the reach, which is the threshold minus it.
            (
                "days",
                timedelta(days=3),
                "Backfills on this project can only reach back 2 days, because older events are dropped. "
                "Try a more recent range.",
            ),
            (
                "fractional_days",
                timedelta(days=1, hours=12),
                "Backfills on this project can only reach back 12 hours, because older events are dropped. "
                "Try a more recent range.",
            ),
            # The margin alone leaves no window at all, so the project cannot backfill anything.
            (
                "threshold_at_the_margin",
                timedelta(days=1),
                "Backfills are not available for this project because it drops events older than 1 day.",
            ),
            # A reach under an hour would render as "about 0 hours", so it is refused instead.
            (
                "reach_under_an_hour",
                timedelta(days=1, minutes=30),
                "Backfills are not available for this project because it drops events older than about 1 day.",
            ),
            (
                "threshold_under_the_margin",
                timedelta(hours=6),
                "Backfills are not available for this project because it drops events older than 6 hours.",
            ),
        ]
    )
    def test_rejects_a_window_entirely_older_than_the_drop_threshold(self, _case, threshold, expected_detail):
        self.team.drop_events_older_than = threshold
        self.team.save()
        now = timezone.now()
        body = _body(
            window_start=(now - timedelta(days=10)).isoformat(),
            window_end=(now - timedelta(days=9)).isoformat(),
        )

        response = self.client.post(f"{self.url}/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == expected_detail
        assert EvaluationBackfill.objects.unscoped().count() == 0

    @parameterized.expand(["create", "estimate"])
    def test_a_condition_hogql_cannot_compile_is_a_bad_request(self, case):
        body = _body(
            conditions=[
                {"id": "c1", "properties": [{"type": "hogql", "key": "not ! valid"}], "rollout_percentage": 100}
            ]
        )
        path = f"{self.url}/" if case == "create" else f"{self.url}/estimate/"

        response = self.client.post(path, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == "A condition could not be applied. Check the filters and try again."
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
        self.viewer = User.objects.create_and_join(self.organization, "backfill-viewer@posthog.com", "testtest")
        self.viewer_membership = OrganizationMembership.objects.get(user=self.viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            resource_id=None,
            access_level="viewer",
            organization_member=self.viewer_membership,
        )
        self.client.force_login(self.viewer)

    def _grant_editor_on_this_evaluation(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            resource_id=str(self.evaluation.id),
            access_level="editor",
            organization_member=self.viewer_membership,
        )

    def _authenticate_viewer_with_api_key(self, scopes: list[str]) -> None:
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="backfill key", user=self.viewer, secure_value=hash_key_value(key_value), scopes=scopes
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key_value}")

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
        self._grant_editor_on_this_evaluation()

        created = self.client.post(f"{self.url}/", _body(), format="json")

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        assert EvaluationBackfill.objects.unscoped().count() == 1

    @patch(f"{API_MODULE}.count_backfill_candidates", return_value=4)
    @patch(f"{API_MODULE}.sync_connect")
    def test_a_personal_api_key_reaches_the_same_per_evaluation_grant_as_a_session(self, connect, _count):
        connect.return_value = _temporal_client()
        self._grant_editor_on_this_evaluation()
        self._authenticate_viewer_with_api_key(["evaluation:write"])

        created = self.client.post(f"{self.url}/", _body(), format="json")

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        assert EvaluationBackfill.objects.unscoped().count() == 1

    @parameterized.expand(
        [
            ("without_the_grant", False, ["evaluation:write"]),
            ("read_scope_only", True, ["evaluation:read"]),
        ]
    )
    def test_a_personal_api_key_is_still_refused_without_write_access(self, _case, grant_editor, scopes):
        if grant_editor:
            self._grant_editor_on_this_evaluation()
        self._authenticate_viewer_with_api_key(scopes)

        created = self.client.post(f"{self.url}/", _body(), format="json")

        assert created.status_code == status.HTTP_403_FORBIDDEN, created.json()
        assert EvaluationBackfill.objects.unscoped().count() == 0


class TestBackfillThrottleBuckets(APIBaseTest):
    @parameterized.expand(
        [
            ("estimate", AIObservabilityBackfillEstimateThrottle),
            ("create", AIObservabilityBackfillCreateThrottle),
        ]
    )
    def test_two_users_on_one_project_do_not_share_a_bucket(self, _case, throttle_class):
        other_user = User.objects.create_and_join(self.organization, "backfill-second@posthog.com", "testtest")
        view = SimpleNamespace(team_id=self.team.id)
        throttle = throttle_class()

        keys = [throttle.get_cache_key(_throttle_request(user), view) for user in (self.user, other_user, self.user)]

        assert keys[0] != keys[1]
        assert keys[0] == keys[2]

    @parameterized.expand(
        [
            ("estimate", AIObservabilityBackfillEstimateThrottle),
            ("create", AIObservabilityBackfillCreateThrottle),
        ]
    )
    def test_each_personal_api_key_gets_its_own_bucket(self, _case, throttle_class):
        view = SimpleNamespace(team_id=self.team.id)
        throttle = throttle_class()
        first_key, second_key = (self._personal_api_key(f"key-{index}") for index in (1, 2))

        session = throttle.get_cache_key(_throttle_request(self.user), view)
        first = throttle.get_cache_key(_throttle_request(self.user, personal_api_key=first_key), view)
        second = throttle.get_cache_key(_throttle_request(self.user, personal_api_key=second_key), view)

        assert len({session, first, second}) == 3

    def _personal_api_key(self, label: str) -> str:
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label=label, user=self.user, secure_value=hash_key_value(key_value), scopes=["evaluation:write"]
        )
        return key_value
