import json
from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.cdp.backend.facade.clickhouse import INSERT_HOG_INVOCATION_RESULT_SQL
from products.customer_analytics.backend.test.factories import create_account
from products.workflows.backend.facade.testing import create_workflow_for_test


class TestAccountAutomations(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.account = create_account(team_id=self.team.pk, name="Example", external_id="example")
        self.flow = create_workflow_for_test(
            team_id=self.team.pk, name="Welcome", actions=[{"id": "wait", "type": "delay"}, {"id": "a", "type": "exit"}]
        )
        self.url = f"/api/projects/{self.team.pk}/accounts/{self.account.id}/automations/"

    def seed(
        self,
        invocation_id: str,
        *,
        status: str = "succeeded",
        version: int = 1,
        deleted: int = 0,
        event: str = "$account_updated",
        distinct_id: str = "staff",
        account_audience: bool = False,
        team_id: int | None = None,
        parent_run_id: str = "",
        event_uuid: str = "",
        trigger_age_days: int = 3,
        schedule_age_days: int = 0,
    ) -> None:
        now = timezone.now()
        sync_execute(
            INSERT_HOG_INVOCATION_RESULT_SQL,
            {
                "team_id": team_id or self.team.pk,
                "function_kind": "hog_flow",
                "function_id": str(self.flow.id),
                "invocation_id": invocation_id,
                "parent_run_id": parent_run_id,
                "status": status,
                "attempts": 1,
                "is_retry": 0,
                "scheduled_at": now - timedelta(days=schedule_age_days),
                "first_scheduled_at": now - timedelta(days=trigger_age_days),
                "started_at": now,
                "finished_at": now,
                "duration_ms": 1,
                "error_kind": "",
                "error_message": "",
                "event_uuid": event_uuid,
                "distinct_id": distinct_id,
                "person_id": "",
                "version": version,
                "is_deleted": deleted,
                "invocation_globals": json.dumps(
                    {
                        "accountAudience": account_audience,
                        "event": {
                            "event": event,
                            "distinct_id": distinct_id,
                            "properties": {"account_external_id": "example"},
                        },
                    }
                ),
            },
        )

    def test_retained_repeat_runs_respect_terminal_deleted_and_expired_records(self) -> None:
        running_id, completed_id, deleted_id, expired_id, removed_id = [str(uuid4()) for _ in range(5)]
        self.seed(running_id, status="running", distinct_id=f"account:{self.account.id}", trigger_age_days=45)
        self.seed(completed_id, status="running", distinct_id=f"account:{self.account.id}")
        self.seed(completed_id, status="succeeded", version=2, distinct_id=f"account:{self.account.id}")
        self.seed(deleted_id, deleted=1, distinct_id=f"account:{self.account.id}")
        self.seed(removed_id, status="running", distinct_id=f"account:{self.account.id}")
        self.seed(removed_id, deleted=1, version=2, distinct_id="", event="")
        self.seed(
            expired_id,
            status="running",
            distinct_id=f"account:{self.account.id}",
            trigger_age_days=45,
            schedule_age_days=31,
        )
        now = timezone.now()
        for run_id in [running_id, completed_id]:
            for i, message in enumerate(
                ["Executing action wait", f"Workflow will pause until {(now + timedelta(days=1)).isoformat()}"]
            ):
                sync_execute(
                    INSERT_LOG_ENTRY_SQL,
                    {
                        "team_id": self.team.pk,
                        "log_source": "hog_flow",
                        "log_source_id": str(self.flow.id),
                        "instance_id": run_id,
                        "timestamp": now + timedelta(seconds=i),
                        "level": "info",
                        "message": message,
                    },
                )
        response = self.client.get(self.url)
        assert response.status_code == 200, response.content
        result = {row["invocation_id"]: row for row in response.json()["results"]}
        assert set(result) == {running_id, completed_id}
        assert result[running_id]["expected_resume_at"] is not None
        assert result[completed_id]["status"] == "succeeded"
        assert result[completed_id]["expected_resume_at"] is None
        assert result[running_id]["triggered_at"].startswith((now - timedelta(days=45)).strftime("%Y-%m-%d"))
        assert result[running_id]["last_completed_step_at"] is None

    @parameterized.expand(["Finish", None])
    def test_account_batch_logs_and_person_event_exclusion(self, step_name: str | None) -> None:
        self.flow = create_workflow_for_test(
            team_id=self.team.pk,
            name="Batch workflow",
            actions=[{"id": "a", "type": "exit", **({"name": step_name} if step_name else {})}],
        )
        batch_id, person_id = str(uuid4()), str(uuid4())
        self.seed(
            batch_id,
            event="$batch_hog_flow_invocation",
            distinct_id="example",
            account_audience=True,
            parent_run_id="batch-parent",
        )
        self.seed(person_id, event="$pageview", distinct_id="example")
        now = timezone.now()
        for i, message in enumerate(["Executing action a", "Workflow completed"]):
            sync_execute(
                INSERT_LOG_ENTRY_SQL,
                {
                    "team_id": self.team.pk,
                    "log_source": "hog_flow",
                    "log_source_id": "batch-parent",
                    "instance_id": batch_id,
                    "timestamp": now + timedelta(seconds=i),
                    "level": "info",
                    "message": message,
                },
            )
        result = self.client.get(self.url).json()["results"]
        assert [row["invocation_id"] for row in result] == [batch_id]
        assert result[0]["last_completed_step_at"] is not None
        assert result[0]["last_completed_step_name"] == step_name

    def test_account_lookup_is_team_scoped(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        response = self.client.get(self.url.replace(f"/{self.team.pk}/", f"/{other_team.pk}/"))
        assert response.status_code == 404

    @parameterized.expand([0, 45])
    def test_user_triggered_account_event_is_discovered_by_event_uuid(self, event_age_days: int) -> None:
        event_uuid = _create_event(
            team=self.team,
            event="$account_updated",
            distinct_id="staff",
            timestamp=timezone.now() - timedelta(days=event_age_days),
            properties={"account_external_id": "example"},
        )
        invocation_id = str(uuid4())
        self.seed(invocation_id, event_uuid=event_uuid)
        result = self.client.get(self.url).json()["results"]
        assert [row["invocation_id"] for row in result] == [invocation_id]

    def test_restricted_workflow_names_and_runs_are_hidden(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        reader = User.objects.create_and_join(self.organization, "reader@example.com", "testtest")
        member = OrganizationMembership.objects.get(user=reader, organization=self.organization)
        AccessControl.objects.create(team=self.team, resource="hog_flow", access_level="none")
        visible = create_workflow_for_test(team_id=self.team.pk, name="Visible")
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=str(visible.id),
            organization_member=member,
            access_level="viewer",
        )
        self.seed(str(uuid4()), distinct_id=f"account:{self.account.id}")
        self.client.force_login(reader)
        response = self.client.get(self.url)
        assert response.status_code == 200, response.content
        assert response.json()["results"] == []

    @parameterized.expand(["hog_flow:read", "person:read", "event:read"])
    def test_api_key_requires_workflow_and_data_scopes(self, missing_scope: str) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Accounts only",
            secure_value=hash_key_value(value),
            scopes=[
                scope
                for scope in ["account:read", "hog_flow:read", "person:read", "event:read"]
                if scope != missing_scope
            ],
        )
        self.client.logout()
        response = self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {value}")
        assert response.status_code == 403
