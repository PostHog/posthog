from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework.response import Response

from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import OrganizationMembership, User

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.models import CustomerTask, CustomerTaskActivity
from products.workflows.backend.models import HogFlow

SECRET = "test-customer-tasks-report-key"


@override_settings(CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRETS=[SECRET])
class TestWorkflowCustomerTaskReports(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.owner = User.objects.create_and_join(self.organization, "loop-owner@example.com", "testpassword")
        self.workflow = HogFlow.objects.create(
            team=self.team, created_by=self.owner, name="Renewal brief loop", trigger={"type": "schedule"}
        )
        self.task = CustomerTask.objects.for_team(self.team.id).create(
            team=self.team,
            name="Draft the renewal brief",
            assigned_to_agent=True,
            properties={"agent": {"assigned_by_id": self.user.id, "assigned_at": "2026-09-01T09:00:00Z"}},
        )
        self.flag = patch(
            "products.customer_analytics.backend.facade.workflow_customer_tasks.posthog_feature_flag_enabled",
            return_value=True,
        )
        self.flag.start()
        self.addCleanup(self.flag.stop)

    def _token(self, **claims: Any) -> str:
        return encode_jwt(
            {
                "team_id": self.team.id,
                "hog_flow_id": str(self.workflow.id),
                "idempotency_key": "run:report:0",
                "customer_task_id": str(self.task.id),
                **claims,
            },
            timedelta(minutes=5),
            PosthogJwtAudience.CUSTOMER_TASKS_REPORT,
            signing_key=SECRET,
        )

    def _report(
        self, data: dict[str, Any] | None = None, token: str | None = None, task_id: UUID | None = None
    ) -> Response:
        return self.client.post(
            f"/api/projects/{self.team.id}/workflow_customer_tasks/{task_id or self.task.id}/report/",
            {"report": "Drafted the brief and attached the usage summary.", "outcome": "completed", **(data or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or self._token()}",
        )

    def _reports(self) -> list[CustomerTaskActivity]:
        return list(
            CustomerTaskActivity.objects.for_team(self.team.id)
            .filter(task=self.task, activity_type="agent_report")
            .order_by("created_at")
        )

    def test_completed_report_closes_the_task_once(self) -> None:
        response = self._report({"task_id": "task-9", "task_run_id": "run-9"})

        assert response.status_code == 200, response.data
        assert response.data["id"] == str(self.task.id)
        self.task.refresh_from_db()
        assert self.task.status == "completed"
        assert self.task.completed_at is not None
        assert self.task.assigned_to_agent is True
        assert self.task.properties["agent"]["outcome"] == "completed"
        reports = self._reports()
        assert len(reports) == 1
        assert reports[0].actor is None
        changes = {change["field"]: change for change in reports[0].changes}
        assert changes["agent_report"]["after"]["report"] == "Drafted the brief and attached the usage summary."
        assert changes["agent_report"]["after"]["task_run_id"] == "run-9"
        assert changes["status"]["after"] == "completed"

        repeated = self._report({"report": "A retry must not add a second report."})
        assert repeated.status_code == 200, repeated.data
        assert len(self._reports()) == 1

        later_run = self._report(
            {"report": "A later run still leaves its report."}, token=self._token(idempotency_key="run:report:1")
        )
        assert later_run.status_code == 200, later_run.data
        reports = self._reports()
        assert len(reports) == 2
        assert [change["field"] for change in reports[1].changes] == ["agent_report"]
        self.task.refresh_from_db()
        assert self.task.status == "completed"

    def test_needs_human_hands_the_task_back_to_the_assigner(self) -> None:
        response = self._report({"outcome": "needs_human"})

        assert response.status_code == 200, response.data
        self.task.refresh_from_db()
        assert self.task.status == "open"
        assert self.task.assigned_to_agent is False
        assert self.task.assigned_to == self.user
        assert self.task.properties["agent"]["outcome"] == "needs_human"
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        assert AccessControl.objects.filter(
            team=self.team,
            resource="customer_task",
            resource_id=str(self.task.id),
            organization_member=membership,
            access_level="editor",
        ).exists()
        assert {change["field"] for change in self._reports()[0].changes} == {
            "agent_report",
            "assigned_to",
            "assigned_to_agent",
        }

    def test_report_after_a_person_took_the_task_back_is_kept_without_changing_it(self) -> None:
        colleague = User.objects.create_and_join(self.organization, "colleague@example.com", "testpassword")
        CustomerTask.objects.for_team(self.team.id).filter(id=self.task.id).update(
            assigned_to=colleague, assigned_to_agent=False, status="in_progress"
        )

        response = self._report()

        assert response.status_code == 200, response.data
        self.task.refresh_from_db()
        assert self.task.status == "in_progress"
        assert self.task.assigned_to == colleague
        assert [change["field"] for change in self._reports()[0].changes] == ["agent_report"]

    def test_only_the_loop_the_task_names_can_report(self) -> None:
        other_loop = HogFlow.objects.create(
            team=self.team, created_by=self.owner, name="Another loop", trigger={"type": "schedule"}
        )
        CustomerTask.objects.for_team(self.team.id).filter(id=self.task.id).update(
            properties={"agent": {"assigned_by_id": self.user.id, "hog_flow_id": str(other_loop.id)}}
        )

        refused = self._report()
        assert refused.status_code == 403, refused.data
        assert self._reports() == []

        accepted = self._report(token=self._token(hog_flow_id=str(other_loop.id)))
        assert accepted.status_code == 200, accepted.data
        assert len(self._reports()) == 1

    @parameterized.expand(
        [
            ("another task", {"customer_task_id": str(uuid4())}, 401),
            ("no invocation", {"idempotency_key": ""}, 401),
            ("no workflow", {"hog_flow_id": "not-a-uuid"}, 401),
            ("another team", {"team_id": 0}, 401),
        ]
    )
    def test_rejects_tokens_that_do_not_fit_the_request(
        self, _name: str, claims: dict[str, Any], expected_status: int
    ) -> None:
        response = self._report(token=self._token(**claims))

        assert response.status_code == expected_status, response.data
        assert self._reports() == []

    def test_rejects_create_tokens_and_unknown_tasks(self) -> None:
        create_token = encode_jwt(
            {
                "team_id": self.team.id,
                "hog_flow_id": str(self.workflow.id),
                "idempotency_key": "run:report:0",
                "customer_task_id": str(self.task.id),
            },
            timedelta(minutes=5),
            PosthogJwtAudience.CUSTOMER_TASKS_CREATE,
            signing_key=SECRET,
        )
        assert self._report(token=create_token).status_code == 401

        missing = uuid4()
        assert self._report(token=self._token(customer_task_id=str(missing)), task_id=missing).status_code == 404
        assert self._reports() == []

    def test_the_workflow_owner_needs_editor_access_to_the_task(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            organization_member=OrganizationMembership.objects.get(user=self.owner, organization=self.organization),
            access_level="viewer",
        )

        assert self._report().status_code == 403
        assert self._reports() == []
        self.task.refresh_from_db()
        assert self.task.status == "open"
