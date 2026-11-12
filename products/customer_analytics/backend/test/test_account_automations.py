import gzip
import json
import base64
from datetime import timedelta
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest, _create_event

from django.test import override_settings
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

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.cdp.backend.facade.clickhouse import INSERT_HOG_INVOCATION_RESULT_SQL
from products.customer_analytics.backend.logic.account_automations import (
    ACCOUNT_AUTOMATION_WORKFLOW_TAG,
    get_workflow_steps,
)
from products.customer_analytics.backend.test.factories import create_account
from products.workflows.backend.facade.testing import create_workflow_for_test


class TestAccountAutomations(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.account = create_account(team_id=self.team.pk, name="Example", external_id="example")
        self.flow = create_workflow_for_test(
            team_id=self.team.pk,
            name="Welcome",
            actions=[{"id": "wait", "type": "delay"}, {"id": "a", "type": "exit"}],
            tags=[ACCOUNT_AUTOMATION_WORKFLOW_TAG],
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
        properties: dict[str, str | None] | None = None,
        compressed: bool = True,
    ) -> None:
        now = timezone.now()
        context = json.dumps(
            {
                "accountAudience": account_audience,
                "event": {
                    "event": event,
                    "distinct_id": distinct_id,
                    "properties": properties if properties is not None else {"account_external_id": "example"},
                },
            }
        )
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
                "invocation_globals": base64.b64encode(gzip.compress(context.encode())).decode()
                if compressed
                else context,
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
            tags=[ACCOUNT_AUTOMATION_WORKFLOW_TAG],
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

    @parameterized.expand([("proxy", 101, True), ("without_proxy", 2, False)])
    def test_step_metadata_is_complete_with_and_without_proxy(
        self, _name: str, workflow_count: int, use_proxy: bool
    ) -> None:
        workflows = [
            create_workflow_for_test(
                team_id=self.team.pk,
                name=f"Workflow {index}",
                actions=[{"id": "wait", "type": "delay", "name": f"Wait {index}"}],
            )
            for index in range(workflow_count)
        ]
        with override_settings(
            DEBUG=use_proxy,
            TEST=use_proxy,
            CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST=None,
            CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT=None,
            CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE=None,
            CLICKHOUSE_HOGQL_RDSPROXY_READ_USER=None,
            CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD=None,
        ):
            steps = get_workflow_steps(
                team=self.team,
                workflow_ids={str(flow.id) for flow in workflows},
                user_access_control=UserAccessControl(user=self.user, team=self.team),
            )
        assert {
            workflow_id: [(step.action_id, step.action_type, step.name) for step in actions]
            for workflow_id, actions in steps.items()
        } == {str(flow.id): [("wait", "delay", f"Wait {index}")] for index, flow in enumerate(workflows)}

    @parameterized.expand(
        [
            ("custom_output", 1000, True, True),
            ("custom_failure_output", 1, True, True),
            ("custom_failure_output", 1000, True, True),
            ("runtime_error", 1, False, True),
            ("runtime_skip", 1, False, True),
            ("at_limit", 196, True, False),
            ("overflow", 201, False, False),
        ]
    )
    def test_log_evidence_ignores_custom_output_and_omits_overflow(
        self, kind: str, message_count: int, has_evidence: bool, waiting: bool
    ) -> None:
        run_id = str(uuid4())
        self.seed(run_id, status="running", distinct_id=f"account:{self.account.id}")
        now = timezone.now()
        custom_output = kind.startswith("custom_")
        noise = {
            "custom_failure_output": "[Action:a] skip_count=0 Errored: 0 did not match=0 would not trigger=0",
            "runtime_error": "[Action:a] Errored: failed",
            "runtime_skip": "[Action:a] Skipped due to filter conditions",
        }.get(kind, "custom output " * 1000)
        before_transition = custom_output or kind.startswith("runtime_")
        messages = (
            ["Executing action a"]
            + ([noise] * message_count if before_transition else [])
            + [
                "Workflow moved to action wait",
                "Executing action wait",
                f"Workflow will pause until {(now + timedelta(days=1)).isoformat()}",
            ]
            + ([] if before_transition else ["Executing action wait"] * message_count)
        )
        sync_execute(
            "INSERT INTO log_entries (team_id, log_source, log_source_id, instance_id, timestamp, level, message) VALUES",
            [
                (
                    self.team.pk,
                    "hog_flow",
                    str(self.flow.id),
                    run_id,
                    now + timedelta(microseconds=index),
                    "info",
                    message,
                )
                for index, message in enumerate(messages)
            ],
        )
        response = self.client.get(self.url)
        assert response.status_code == 200, response.content
        result = response.json()["results"][0]
        assert (result["last_completed_step_at"] is not None) == has_evidence
        assert (result["expected_resume_at"] is not None) == waiting

    @parameterized.expand(
        [(0, "example", True), (45, "example", True), (0, None, True), (0, "changed", True), (0, "example", False)]
    )
    def test_user_triggered_account_event_is_discovered_by_event_uuid(
        self, event_age_days: int, external_id: str | None, stable_id: bool
    ) -> None:
        self.account.external_id = external_id
        self.account.save()
        event_uuid = _create_event(
            team=self.team,
            event="$account_updated",
            distinct_id="staff",
            timestamp=timezone.now() - timedelta(days=event_age_days),
            properties={
                **({"account_id": str(self.account.id)} if stable_id else {}),
                "account_external_id": "example",
            },
        )
        invocation_id = str(uuid4())
        self.seed(invocation_id, event_uuid=event_uuid)
        result = self.client.get(self.url).json()["results"]
        assert [row["invocation_id"] for row in result] == [invocation_id]

    @parameterized.expand([True, False])
    def test_account_pages_exclude_person_runs_and_count_all_matches(self, compressed: bool) -> None:
        expected = []
        for age in [3, 1, 2]:
            run_id = str(uuid4())
            self.seed(run_id, distinct_id=f"account:{self.account.id}", trigger_age_days=age, compressed=compressed)
            expected.append((age, run_id))
        self.seed(str(uuid4()), event="$pageview", distinct_id=f"account:{self.account.id}", compressed=compressed)
        self.seed(str(uuid4()), event="$batch_hog_flow_invocation", distinct_id="example", compressed=compressed)
        self.seed(
            str(uuid4()),
            distinct_id="example",
            properties={"account_id": str(uuid4()), "account_external_id": "example"},
            compressed=compressed,
        )
        self.flow = create_workflow_for_test(team_id=self.team.pk, name="Untagged")
        self.seed(str(uuid4()), distinct_id=f"account:{self.account.id}", compressed=compressed)
        response = self.client.get(self.url, {"limit": 1, "offset": 1})
        assert response.status_code == 200, response.content
        assert response.json()["count"] == 3
        assert [row["invocation_id"] for row in response.json()["results"]] == [sorted(expected)[1][1]]
        response = self.client.get(self.url, {"limit": 1, "offset": 3})
        assert response.json()["count"] == 3
        assert response.json()["results"] == []

    def test_restricted_workflow_names_and_runs_are_hidden(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        reader = User.objects.create_and_join(self.organization, "reader@example.com", "testtest")
        member = OrganizationMembership.objects.get(user=reader, organization=self.organization)
        AccessControl.objects.create(team=self.team, resource="hog_flow", access_level="none")
        visible = create_workflow_for_test(team_id=self.team.pk, name="Visible", tags=[ACCOUNT_AUTOMATION_WORKFLOW_TAG])
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=str(visible.id),
            organization_member=member,
            access_level="viewer",
        )
        self.seed(str(uuid4()), distinct_id=f"account:{self.account.id}")
        self.flow = visible
        visible_run_id = str(uuid4())
        self.seed(visible_run_id, distinct_id=f"account:{self.account.id}")
        self.client.force_login(reader)
        response = self.client.get(self.url)
        assert response.status_code == 200, response.content
        assert [row["invocation_id"] for row in response.json()["results"]] == [visible_run_id]
        assert response.json()["results"][0]["workflow_name"] == "Visible"

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
