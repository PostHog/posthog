from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Integration, User
from posthog.models.scoping import team_scope
from posthog.token_bucket import BucketDecision

from products.cloud_agents.backend.facade import api
from products.cloud_agents.backend.facade.contracts import CallerIdentity, RepositoryRef, RunCreateInput
from products.cloud_agents.backend.facade.enums import BillingMode, CallerKind
from products.cloud_agents.backend.logic.status import QUOTA_SWEEP_CANCEL_SOURCE
from products.cloud_agents.backend.models import CloudAgentPreset, CloudAgentRun, TeamCloudAgentsConfig
from products.cloud_agents.backend.tests.base import (
    LOGIC,
    RUN_CONFIG,
    CloudAgentsFlagMixin,
    TasksFakeMixin,
    billing_dto,
    task_run_dto,
)
from products.tasks.backend.facade.cloud_agents import (
    CloudAgentRunNotResumable,
    CloudAgentTaskInvalid,
    get_cloud_agent_task_run,
    list_cloud_agent_task_run_ids,
)
from products.tasks.backend.facade.compute import SandboxSize
from products.tasks.backend.facade.compute_quota import ComputeBillingLimitExceeded
from products.tasks.backend.facade.contracts import SandboxSessionUsageDTO
from products.tasks.backend.facade.inference import InferenceDecision, InferenceUnavailable

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
CREATE_BODY: dict[str, Any] = {"prompt": "Fix the flaky test", "repositories": [{"name": "acme/app"}]}
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}
PR_URL = "https://github.com/acme/app/pull/7"
OWN_SUBSCRIPTION_DECISION = InferenceDecision(
    mode="own_subscription",
    adapter="claude",
    credential_kind="claude_subscription",
    owner_user_id=1,
    run_state_updates={"claude_model_access": "own-subscription"},
    resolved_from_auto=True,
)


class RunsAPITestCase(TasksFakeMixin, CloudAgentsFlagMixin, APIBaseTest):
    def runs_url(self, suffix: str = "") -> str:
        return f"{self.base_url()}/runs/{suffix}"

    def create(self, body: dict[str, Any] | None = None, **extra: Any) -> Any:
        return self.client.post(self.runs_url(), data=body or CREATE_BODY, format="json", **extra)

    def stored_runs(self) -> list[CloudAgentRun]:
        with team_scope(self.team.id):
            return list(CloudAgentRun.objects.order_by("created_at", "id"))


class TestCreateRun(RunsAPITestCase):
    def test_minimal_create_returns_the_full_run(self) -> None:
        with time_machine.travel(NOW, tick=False):
            response = self.create()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        (run,) = self.stored_runs()
        assert response.json() == {
            "id": str(run.id),
            "status": "queued",
            "status_reason": None,
            "status_detail": None,
            "created_at": "2026-10-07T12:00:00Z",
            "started_at": None,
            "ended_at": None,
            "updated_at": "2026-10-07T12:00:00Z",
            "prompt": "Fix the flaky test",
            "repositories": [{"name": "acme/app", "initial_branch": None}],
            "preset": None,
            "config": {
                "model": run.config["model"],
                "reasoning_effort": None,
                "size": {"name": "4x16", "vcpu": 4, "memory_gib": 16, "price_per_hour_usd": "0.368"},
                "inference": "posthog",
                "create_pr": True,
                "idle_minutes": 10,
                "output_schema": None,
                "instructions_applied": False,
            },
            "result": {"pr_url": None, "pr_urls": [], "summary": None, "output": None},
            "cost": {
                "compute_usd": None,
                "inference_usd": None,
                "total_usd": None,
                "vcpu_seconds": "0.000",
                "gib_seconds": "0.000",
                "billing_mode": "billed",
                "inference_billing": "posthog",
                "final": False,
            },
            "agent_sessions": [{"index": 1, "status": "queued", "started_at": None, "ended_at": None}],
            "tags": [],
            "metadata": {},
            "created_by": {"id": self.user.id, "email": self.user.email},
            "caller": "app",
        }
        (call,) = self.tasks.create_calls
        assert call["origin_key"] is None
        assert call["billable"] is True
        assert call["prompt"] == call["title"] == "Fix the flaky test"
        assert call["sandbox_size"] == SandboxSize("4x16")
        assert call["inactivity_timeout_seconds"] == 600
        assert call["extra_run_state"] == {"cloud_agents_run_id": str(run.id)}
        assert (call["model"], call["runtime_adapter"]) == (run.config["model"], "claude")
        assert (call["repository"], call["branch"]) == ("acme/app", None)
        assert (call["reasoning_effort"], call["output_schema"]) == (None, None)
        assert run.task_id is not None
        assert self.tasks.list_run_ids(team_id=self.team.id, task_id=run.task_id) != []

    def test_preset_supplies_everything_but_the_prompt(self) -> None:
        with team_scope(self.team.id):
            preset = CloudAgentPreset.objects.create(
                team=self.team,
                name="Backend",
                repositories=[{"name": "acme/api", "initial_branch": "develop"}],
                instructions="Run the tests.",
                reasoning_effort="high",
                idle_minutes=45,
                output_schema=ANSWER_SCHEMA,
                tags=["be"],
            )
        response = self.create({"prompt": "Fix it", "preset": "backend", "tags": ["ci"]})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["repositories"] == [{"name": "acme/api", "initial_branch": "develop"}]
        assert body["preset"] == {"id": str(preset.id), "name": "Backend"}
        assert body["tags"] == ["be", "ci"]
        assert body["config"]["instructions_applied"] is True
        assert (body["config"]["reasoning_effort"], body["config"]["idle_minutes"]) == ("high", 45)
        assert body["config"]["output_schema"] == ANSWER_SCHEMA
        (call,) = self.tasks.create_calls
        assert call["prompt"] == "<instructions>\nRun the tests.\n</instructions>\n\nFix it"
        assert (call["repository"], call["branch"]) == ("acme/api", "develop")
        assert (call["reasoning_effort"], call["inactivity_timeout_seconds"]) == ("high", 45 * 60)
        assert call["output_schema"] == ANSWER_SCHEMA
        (run,) = self.stored_runs()
        assert (run.repository, run.preset_id) == ("acme/api", preset.id)

    @parameterized.expand(
        [
            ("no_repository", {"prompt": "Fix it"}, "repositories", "repository_required"),
            ("empty_repositories", {"prompt": "Fix it", "repositories": []}, "repositories", "repository_required"),
            (
                "two_repositories",
                {"prompt": "Fix it", "repositories": [{"name": "acme/app"}, {"name": "acme/web"}]},
                "repositories",
                "invalid_input",
            ),
            ("unknown_preset", {**CREATE_BODY, "preset": "nope"}, "preset", "invalid_input"),
            ("idle_minutes_over_the_tasks_limit", {**CREATE_BODY, "idle_minutes": 121}, "idle_minutes", "max_value"),
            (
                "unknown_reasoning_effort",
                {**CREATE_BODY, "reasoning_effort": "extreme"},
                "reasoning_effort",
                "invalid_choice",
            ),
            (
                "output_schema_of_a_string",
                {**CREATE_BODY, "output_schema": {"type": "string"}},
                "output_schema",
                "invalid_input",
            ),
            ("empty_prompt", {**CREATE_BODY, "prompt": ""}, "prompt", "blank"),
            ("unknown_model", {**CREATE_BODY, "model": "not-a-model"}, "model", "invalid_input"),
            (
                "too_many_metadata_pairs",
                {**CREATE_BODY, "metadata": {str(index): "v" for index in range(17)}},
                "metadata",
                "invalid_input",
            ),
        ]
    )
    def test_invalid_request_starts_nothing(
        self, _name: str, body: dict[str, Any], attr: str | None, code: str
    ) -> None:
        response = self.create(body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["attr"], response.json()["code"]) == (attr, code)
        assert self.stored_runs() == []
        assert self.tasks.create_calls == []

    def test_idempotency_key_replays_the_run_and_refuses_a_different_body(self) -> None:
        first = self.create(HTTP_IDEMPOTENCY_KEY="key-1")
        replay = self.create(HTTP_IDEMPOTENCY_KEY="key-1")
        different = self.create({**CREATE_BODY, "prompt": "Other task"}, HTTP_IDEMPOTENCY_KEY="key-1")
        other_key = self.create(HTTP_IDEMPOTENCY_KEY="key-2")

        assert first.status_code == status.HTTP_201_CREATED
        assert "Idempotency-Replayed" not in first.headers
        assert (replay.status_code, replay.headers["Idempotency-Replayed"]) == (status.HTTP_200_OK, "true")
        assert replay.json()["id"] == first.json()["id"]
        assert different.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert different.json()["code"] == "idempotency_key_reused"
        assert other_key.status_code == status.HTTP_201_CREATED
        assert len(self.tasks.create_calls) == 2
        assert self.tasks.create_calls[0]["origin_key"].startswith("ca:")
        assert self.tasks.create_calls[0]["origin_key"] != self.tasks.create_calls[1]["origin_key"]

    def test_replay_does_not_pass_the_gates_again(self) -> None:
        first = self.create(HTTP_IDEMPOTENCY_KEY="key-1")
        self.mocks["runs.cloud_agents_quota_denial"].return_value = "quota_exhausted"
        consumed = self.mocks["limits.consume"].call_count

        replay = self.create(HTTP_IDEMPOTENCY_KEY="key-1")

        assert (replay.status_code, replay.json()["id"]) == (status.HTTP_200_OK, first.json()["id"])
        assert self.mocks["limits.consume"].call_count == consumed

    def test_concurrent_request_with_the_same_key_replays_the_stored_run(self) -> None:
        first = self.create(HTTP_IDEMPOTENCY_KEY="key-1")
        with team_scope(self.team.id):
            winner = CloudAgentRun.objects.get(id=first.json()["id"])
            winner.idempotency_key = None
            winner.save()

        def store_the_winner(**kwargs: Any) -> InferenceDecision:
            # The other request stores its run after this request looked for the key and before it inserts.
            CloudAgentRun.all_teams.filter(id=winner.id).update(idempotency_key="key-1")
            return self.mocks["runs.resolve_inference"].return_value

        self.mocks["runs.resolve_inference"].side_effect = store_the_winner
        response = self.create(HTTP_IDEMPOTENCY_KEY="key-1")

        assert (response.status_code, response.json()["id"]) == (status.HTTP_200_OK, first.json()["id"])
        assert len(self.stored_runs()) == 1
        assert len(self.tasks.create_calls) == 1
        self.mocks["limits.refund"].assert_called_once()

    @parameterized.expand([("empty", " "), ("too_long", "k" * 101)])
    def test_invalid_idempotency_key_is_rejected(self, _name: str, key: str) -> None:
        response = self.create(HTTP_IDEMPOTENCY_KEY=key)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "Idempotency-Key"

    @parameterized.expand(
        [
            ("resets_soon", timedelta(hours=1), "3600"),
            ("reset_is_capped_at_a_day", timedelta(days=10), "86400"),
            ("reset_unknown", None, None),
        ]
    )
    def test_quota_denied(self, _name: str, reset_in: timedelta | None, retry_after: str | None) -> None:
        self.mocks["runs.cloud_agents_quota_denial"].return_value = "quota_exhausted"
        self.mocks["runs.cloud_agents_quota_reset_at"].return_value = NOW + reset_in if reset_in else None
        with time_machine.travel(NOW, tick=False):
            response = self.create()

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.json()["code"] == "usage_limited"
        assert response.headers.get("Retry-After") == retry_after
        assert self.tasks.create_calls == []
        self.mocks["limits.consume"].assert_not_called()

    def test_deactivated_organization_is_refused(self) -> None:
        self.mocks["runs.cloud_agents_quota_denial"].return_value = "organization_deactivated"
        response = self.create()
        assert (response.status_code, response.json()["code"]) == (403, "organization_deactivated")

    def test_create_rate_limited(self) -> None:
        self.mocks["limits.consume"].return_value = BucketDecision(
            allowed=False, remaining=0, limit=10, retry_after=42, reset=600
        )
        response = self.create()

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert (response.json()["code"], response.headers["Retry-After"]) == ("create_rate_limited", "42")
        assert self.tasks.create_calls == []

    def test_concurrency_limit_starts_nothing_and_refunds_the_rate(self) -> None:
        with team_scope(self.team.id):
            TeamCloudAgentsConfig.objects.create(team=self.team, max_concurrent_runs=1)
        assert self.create().status_code == status.HTTP_201_CREATED

        response = self.create()

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert (response.json()["code"], response.headers["Retry-After"]) == ("concurrency_limited", "30")
        assert len(self.tasks.create_calls) == 1
        assert len(self.stored_runs()) == 1
        self.mocks["limits.refund"].assert_called_once()

    @parameterized.expand(
        [
            (
                "inference_unavailable",
                "runs.resolve_inference",
                InferenceUnavailable("Connect your Claude subscription first.", code="credential_missing"),
                "inference",
            ),
            (
                "tasks_refuses_the_model",
                "runs.create_cloud_agent_task",
                CloudAgentTaskInvalid("This model is not available to you.", attr="model"),
                "model",
            ),
            (
                "tasks_refuses_the_output_schema",
                "runs.create_cloud_agent_task",
                CloudAgentTaskInvalid("The output schema is too large.", attr="output_schema"),
                "output_schema",
            ),
        ]
    )
    def test_refused_start_leaves_no_run_and_refunds_the_rate(
        self, _name: str, target: str, error: Exception, attr: str
    ) -> None:
        self.mocks[target].side_effect = error
        response = self.create({**CREATE_BODY, "inference": "own_subscription"}, HTTP_IDEMPOTENCY_KEY="key-1")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["attr"], response.json()["detail"]) == (attr, str(error))
        assert self.stored_runs() == []
        self.mocks["limits.refund"].assert_called_once()

    def test_failed_start_leaves_no_run_so_the_same_key_can_try_again(self) -> None:
        self.mocks["runs.create_cloud_agent_task"].side_effect = RuntimeError("database is down")
        self.client.raise_request_exception = False
        failed = self.create(HTTP_IDEMPOTENCY_KEY="key-1")
        self.mocks["runs.create_cloud_agent_task"].side_effect = self.tasks.create

        retried = self.create(HTTP_IDEMPOTENCY_KEY="key-1")

        assert failed.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert retried.status_code == status.HTTP_201_CREATED
        assert [str(run.id) for run in self.stored_runs()] == [retried.json()["id"]]

    def test_own_subscription_run_reports_who_pays_for_inference(self) -> None:
        self.mocks["runs.resolve_inference"].return_value = OWN_SUBSCRIPTION_DECISION
        body = self.create({**CREATE_BODY, "inference": "auto"}).json()

        assert body["config"]["inference"] == "own_subscription"
        assert self.tasks.create_calls[0]["inference_state"] == {"claude_model_access": "own-subscription"}
        assert self.mocks["runs.resolve_inference"].call_args.kwargs["requested"] == "auto"

    def test_internal_caller_is_not_billed_and_skips_the_quota(self) -> None:
        self.mocks["runs.cloud_agents_quota_denial"].return_value = "quota_exhausted"
        caller = CallerIdentity(
            user_id=self.user.id, distinct_id=None, kind=CallerKind.INTERNAL, billable=False, product="signals"
        )

        data = RunCreateInput(prompt="Fix the flaky test", repositories=[RepositoryRef(name="acme/app")])
        run, replayed = api.start_run(self.team.id, caller, data)

        assert replayed is False
        assert self.tasks.create_calls[0]["billable"] is False
        assert run.cost.billing_mode == BillingMode.UNBILLED
        assert run.caller_kind == CallerKind.INTERNAL
        assert api.get_run(self.team.id, run.id).cost.billing_mode == BillingMode.UNBILLED


@patch("products.tasks.backend.models.TaskRun.publish_stream_state_event", MagicMock())
@patch("products.tasks.backend.temporal.client.execute_task_processing_workflow", MagicMock())
class TestCreateRunWithTasks(CloudAgentsFlagMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        Integration.objects.create(team=self.team, kind="github", config={})

    def test_create_starts_a_tasks_run_without_the_desktop_access_gate(self) -> None:
        denied = AssertionError("Cloud Agents must not consult the PostHog Desktop access gate")
        with (
            patch("products.tasks.backend.facade.access.get_desktop_access_decision", side_effect=denied),
            patch("products.tasks.backend.facade.access.code_access_required_response", side_effect=denied),
            patch("products.tasks.backend.facade.access.usage_limit_response", side_effect=denied),
            patch("products.tasks.backend.access.get_desktop_access_decision", side_effect=denied),
            patch(
                f"{LOGIC}.limits.consume",
                return_value=BucketDecision(allowed=True, remaining=9, limit=10, retry_after=0, reset=0),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(f"{self.base_url()}/runs/", data=CREATE_BODY, format="json")
            read = self.client.get(f"{self.base_url()}/runs/{response.json()['id']}/")
            listed = self.client.get(f"{self.base_url()}/runs/?status=queued")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        with team_scope(self.team.id):
            run = CloudAgentRun.objects.get(id=response.json()["id"])
        assert run.task_id is not None
        (task_run_id,) = list_cloud_agent_task_run_ids(team_id=self.team.id, task_id=run.task_id)
        task_run = get_cloud_agent_task_run(team_id=self.team.id, run_id=task_run_id)
        assert task_run is not None
        assert task_run.state["cloud_agents_run_id"] == str(run.id)
        # The status, the sessions and the cost come from the rows of Tasks, with no copy in this product.
        for body in (response.json(), read.json(), listed.json()["results"][0]):
            assert (body["id"], body["status"], body["cost"]["billing_mode"]) == (str(run.id), "queued", "billed")
            assert [session["status"] for session in body["agent_sessions"]] == ["queued"]


class TestReadRuns(RunsAPITestCase):
    def test_list_filters(self) -> None:
        with team_scope(self.team.id):
            preset = CloudAgentPreset.objects.create(team=self.team, name="Backend")
        with time_machine.travel(NOW - timedelta(days=2), tick=False):
            old = self.make_run(repository="acme/api", tags=["ci"], preset=preset)
        with time_machine.travel(NOW - timedelta(days=1), tick=False):
            merged = self.make_run(task_status="completed", tags=["ci"])
            self.tasks.set_status(
                self.tasks.current_run_id(merged), "completed", output={"pr_url": PR_URL, "pr_state": "merged"}
            )
            cancelled = self.make_run(task_status="cancelled")
        with time_machine.travel(NOW, tick=False):
            new = self.make_run(task_status="completed")
            failed = self.make_run(task_status="failed")
        idle = sorted([new, failed], key=lambda run: str(run.id), reverse=True)
        done = sorted([merged, cancelled], key=lambda run: str(run.id), reverse=True)
        cases: list[tuple[str, list[CloudAgentRun]]] = [
            ("", [*idle, *done, old]),
            ("?status=idle", idle),
            ("?status=done", done),
            ("?status=queued", [old]),
            (f"?preset_id={preset.id}", [old]),
            ("?repository=ACME/API", [old]),
            ("?repository=api", [old]),
            ("?repository=acme", [*idle, *done, old]),
            ("?tag=ci", [merged, old]),
            ("?tag=c", []),
            ("?created_after=2026-10-07T00:00:00Z", idle),
            ("?created_before=2026-10-06T00:00:00Z", [old]),
            ("?status=queued&repository=api", [old]),
            ("?status=idle&repository=api", []),
            ("?status=done&tag=ci", [merged]),
            ("?status=idle&created_before=2026-10-07T00:00:00Z", []),
            ("?status=running", []),
        ]
        for query, expected in cases:
            body = self.client.get(self.runs_url(query)).json()
            assert [row["id"] for row in body["results"]] == [str(run.id) for run in expected], query
            assert body["count"] == len(expected), query

    def test_idle_and_done_filters_count_every_matching_run_and_read_one_page(self) -> None:
        with time_machine.travel(NOW, tick=False):
            idle = [self.make_run(task_status="completed") for _ in range(3)]
            self.make_run(task_status="cancelled")
            self.make_run(task_status="in_progress")
        self.tasks.state_reads.clear()

        page = self.client.get(self.runs_url("?status=idle&limit=2")).json()

        assert page["count"] == 3
        assert [row["id"] for row in page["results"]] == sorted((str(run.id) for run in idle), reverse=True)[:2]
        # One read tells idle from done for the ended runs, and one read is for the page.
        assert [len(task_ids) for task_ids in self.tasks.state_reads] == [4, 2]

    @parameterized.expand([("paused",), ("completed",), ("failed",), ("cancelled",)])
    def test_list_rejects_an_unknown_status(self, value: str) -> None:
        response = self.client.get(self.runs_url(f"?status={value}"))
        assert (response.status_code, response.json()["attr"]) == (status.HTTP_400_BAD_REQUEST, "status")

    def test_list_pages_do_not_repeat_or_skip_runs_created_at_the_same_instant(self) -> None:
        with time_machine.travel(NOW, tick=False):
            runs = [self.make_run() for _ in range(5)]
        expected = sorted((str(run.id) for run in runs), reverse=True)

        paged: list[str] = []
        for offset in range(0, 6, 2):
            page = self.client.get(self.runs_url(f"?limit=2&offset={offset}")).json()
            assert page["count"] == 5
            paged.extend(row["id"] for row in page["results"])
        assert paged == expected
        # One read of the states and one of the costs for each page, not for each run.
        assert [len(task_ids) for task_ids in self.tasks.state_reads] == [2, 2, 1]
        assert [len(task_ids) for task_ids in self.tasks.billing_reads] == [2, 2, 1]

    def test_retrieve_shows_the_status_and_the_cost_that_tasks_has_now(self) -> None:
        with time_machine.travel(NOW, tick=False):
            run = self.make_run()
            self.tasks.billing = billing_dto(compute_cost_cents=12, inference_cost_cents=30)
            queued = self.client.get(self.runs_url(f"{run.id}/")).json()
            self.tasks.set_status(self.tasks.current_run_id(run), "in_progress")
            running = self.client.get(self.runs_url(f"{run.id}/")).json()

        assert (queued["status"], queued["started_at"]) == ("queued", None)
        assert (running["status"], running["started_at"]) == ("running", "2026-10-07T12:00:00Z")
        assert running["cost"] == {
            "compute_usd": "0.1200",
            "inference_usd": "0.3000",
            "total_usd": "0.4200",
            "vcpu_seconds": "0.000",
            "gib_seconds": "0.000",
            "billing_mode": "billed",
            "inference_billing": "posthog",
            "final": False,
        }

    def test_run_usage_lists_the_sandbox_sessions(self) -> None:
        run = self.make_run()
        self.tasks.billing = billing_dto(
            compute_cost_cents=37,
            inference_cost_cents=None,
            inference_billing="own_subscription",
            vcpu_seconds=Decimal("3600"),
            gib_seconds=Decimal("14400"),
            sessions=(
                SandboxSessionUsageDTO(
                    cpu_cores=4,
                    memory_gb=16,
                    started_at=NOW,
                    ended_at=NOW + timedelta(hours=1),
                    seconds=3600,
                    cost_cents=37,
                    waived=False,
                ),
            ),
        )
        response = self.client.get(self.runs_url(f"{run.id}/usage/"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "run_id": str(run.id),
            "cost": {
                "compute_usd": "0.3700",
                "inference_usd": None,
                "total_usd": "0.3700",
                "vcpu_seconds": "3600.000",
                "gib_seconds": "14400.000",
                "billing_mode": "billed",
                "inference_billing": "own_subscription",
                "final": False,
            },
            "sessions": [
                {
                    "vcpu": "4",
                    "memory_gib": "16",
                    "started_at": "2026-10-07T12:00:00Z",
                    "ended_at": "2026-10-07T13:00:00Z",
                    "seconds": 3600,
                    "cost_usd": "0.3700",
                    "waived": False,
                }
            ],
        }

    @parameterized.expand(
        [
            ("newest_session_fits", [None, [{"n": 1}, {"n": 2}]], [{"n": 1}, {"n": 2}], False, 1),
            ("only_the_first_session_fits", [[{"n": 1}], None], [{"n": 1}], True, 2),
            ("nothing_fits", [None, None], [], True, 2),
        ]
    )
    def test_events_as_json(
        self, _name: str, history_by_session: list[Any], events: list[Any], truncated: bool, reads: int
    ) -> None:
        run = self.make_run(task_status="completed")
        first_id = self.tasks.current_run_id(run)
        second = task_run_dto(team_id=self.team.id, task_id=run.task_id)
        self.tasks.runs[second.id] = second
        history = dict(zip([first_id, second.id], history_by_session))
        self.mocks["runs.read_task_run_history"].side_effect = lambda run_id, *args, **kwargs: history[run_id]

        response = self.client.get(self.runs_url(f"{run.id}/events/"))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"events": events, "truncated": truncated}
        # The newest session is read first, because its history holds the sessions before it.
        assert self.mocks["runs.read_task_run_history"].call_args_list[0].args[0] == second.id
        assert self.mocks["runs.read_task_run_history"].call_count == reads

    @parameterized.expand(
        [
            ("accept_any", "", "*/*"),
            ("accept_json", "", "application/json"),
            ("format_json", "?format=json", None),
        ]
    )
    def test_events_default_to_json(self, _name: str, query: str, accept: str | None) -> None:
        run = self.make_run(task_status="completed")
        self.mocks["runs.read_task_run_history"].return_value = [{"n": 1}]

        url = self.runs_url(f"{run.id}/events/{query}")
        response = self.client.get(url, HTTP_ACCEPT=accept) if accept is not None else self.client.get(url)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response["Content-Type"].startswith("application/json")
        assert response.json() == {"events": [{"n": 1}], "truncated": False}

    def test_events_stream_sends_the_run_frame_then_the_tasks_stream(self) -> None:
        run = self.make_run(task_status="in_progress")
        source = object()

        async def tasks_stream(stream: object) -> Any:
            assert stream is source
            yield b"id: 7\ndata: {}\n\n"

        with (
            patch(f"{LOGIC}.streams.prepare_task_run_sse_stream", return_value=source) as prepare,
            patch(f"{LOGIC}.streams.task_run_sse_stream", tasks_stream),
        ):
            response = self.client.get(
                self.runs_url(f"{run.id}/events/?start=latest"),
                HTTP_ACCEPT="text/event-stream",
                HTTP_LAST_EVENT_ID="6",
            )

            body = b"".join(response.streaming_content)  # type: ignore[attr-defined]

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"].startswith("text/event-stream")
        frames = body.decode().split("\n\n")
        assert frames[0] == (f'event: run\ndata: {{"id": "{run.id}", "status": "running", "status_reason": null}}')
        assert frames[1] == "id: 7\ndata: {}"
        prepare.assert_called_once_with(
            self.tasks.current_run_id(run), run.task_id, self.team.id, last_event_id="6", start_latest=True
        )


class TestSendMessage(RunsAPITestCase):
    def send(self, run: CloudAgentRun, **extra: Any) -> Any:
        return self.client.post(
            self.runs_url(f"{run.id}/messages/"), data={"content": "Also fix the lint"}, format="json", **extra
        )

    def test_live_run_gets_the_message_in_its_session(self) -> None:
        run = self.make_run(task_status="in_progress")
        response = self.send(run)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert (response.json()["resumed"], response.json()["run"]["id"]) == (False, str(run.id))
        signal = self.mocks["runs.signal_task_run_user_message"]
        signal.assert_called_once_with(
            self.tasks.current_run_id(run),
            run.task_id,
            self.team.id,
            content="Also fix the lint",
            artifact_ids=[],
            actor_user_id=self.user.id,
        )
        assert self.tasks.resume_calls == []

    def test_idle_run_resumes_with_its_stored_configuration(self) -> None:
        run = self.make_run(
            task_status="failed",
            config={**RUN_CONFIG, "size": "8x32", "reasoning_effort": "high", "idle_minutes": 45},
        )
        self.tasks.billing = billing_dto(settled=True)
        previous_id = self.tasks.current_run_id(run)
        stopped = self.client.get(self.runs_url(f"{run.id}/")).json()
        self.tasks.billing = billing_dto(settled=False)
        response = self.send(run)

        assert (stopped["status"], stopped["status_reason"]) == ("idle", "unexpected_failure")
        assert stopped["cost"]["final"] is True
        assert stopped["status_detail"] is not None and stopped["ended_at"] is not None
        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        body = response.json()
        assert body["resumed"] is True
        resumed = body["run"]
        assert (resumed["status"], resumed["status_reason"], resumed["status_detail"]) == ("queued", None, None)
        assert (resumed["ended_at"], resumed["cost"]["final"]) == (None, False)
        assert [(session["index"], session["status"]) for session in resumed["agent_sessions"]] == [
            (1, "ended"),
            (2, "queued"),
        ]
        (call,) = self.tasks.resume_calls
        assert call["previous_run_id"] == previous_id
        assert call["message"] == "Also fix the lint"
        assert (call["sandbox_size"], call["model"]) == (SandboxSize("8x32"), "claude-test-model")
        assert (call["reasoning_effort"], call["inactivity_timeout_seconds"]) == ("high", 45 * 60)
        assert call["extra_run_state"] == {"cloud_agents_run_id": str(run.id)}
        assert (call["user_id"], call["inference_state"]) == (self.user.id, None)
        self.mocks["runs.signal_task_run_user_message"].assert_not_called()
        assert self.tasks.current_run_id(run) != previous_id

    def test_workflow_that_is_gone_resumes_when_the_run_has_ended(self) -> None:
        run = self.make_run(task_status="in_progress")

        def workflow_gone(run_id: UUID, *args: Any, **kwargs: Any) -> bool:
            self.tasks.set_status(run_id, "completed")
            return False

        self.mocks["runs.signal_task_run_user_message"].side_effect = workflow_gone
        response = self.send(run)
        assert (response.status_code, response.json()["resumed"]) == (status.HTTP_202_ACCEPTED, True)

    @parameterized.expand(
        [
            (
                "stopping",
                "in_progress",
                "runs.signal_task_run_user_message",
                RuntimeError("stopping"),
                409,
                "run_stopping",
            ),
            (
                "workflow_gone_and_not_ended",
                "in_progress",
                "runs.signal_task_run_user_message",
                None,
                409,
                "run_stopping",
            ),
            (
                "usage_limit",
                "in_progress",
                "runs.signal_task_run_user_message",
                ComputeBillingLimitExceeded(),
                429,
                "usage_limited",
            ),
            (
                "not_resumable",
                "completed",
                "runs.resume_cloud_agent_task",
                CloudAgentRunNotResumable("The previous run belongs to an earlier owner"),
                409,
                "run_not_resumable",
            ),
        ]
    )
    def test_message_that_cannot_be_delivered(
        self, _name: str, task_status: str, target: str, error: Exception | None, http_status: int, code: str
    ) -> None:
        run = self.make_run(task_status=task_status)
        if error is None:
            self.mocks[target].side_effect = None
            self.mocks[target].return_value = False
        else:
            self.mocks[target].side_effect = error
        response = self.send(run)
        assert (response.status_code, response.json()["code"]) == (http_status, code)

    def test_quota_denied(self) -> None:
        run = self.make_run(task_status="in_progress")
        self.mocks["runs.cloud_agents_quota_denial"].return_value = "quota_exhausted"
        assert self.send(run).status_code == status.HTTP_429_TOO_MANY_REQUESTS
        self.mocks["runs.signal_task_run_user_message"].assert_not_called()

    @parameterized.expand([("live", "in_progress"), ("stopped", "completed")])
    def test_only_the_subscription_owner_continues_an_own_subscription_run(self, _name: str, task_status: str) -> None:
        owner = User.objects.create_and_join(self.organization, "owner@example.com", None)
        run = self.make_run(
            task_status=task_status, created_by=owner, config={**RUN_CONFIG, "inference": "own_subscription"}
        )

        response = self.send(run)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == "credential_owner_required"
        assert "subscription of the user who started it" in response.json()["detail"]
        self.mocks["runs.signal_task_run_user_message"].assert_not_called()
        assert self.tasks.resume_calls == []

    def test_another_user_continues_a_posthog_inference_run_as_its_creator(self) -> None:
        owner = User.objects.create_and_join(self.organization, "owner@example.com", None)
        run = self.make_run(task_status="completed", created_by=owner)
        assert self.send(run).status_code == status.HTTP_202_ACCEPTED
        assert self.tasks.resume_calls[0]["user_id"] == owner.id

    def test_resume_counts_against_the_concurrency_limit(self) -> None:
        with team_scope(self.team.id):
            TeamCloudAgentsConfig.objects.create(team=self.team, max_concurrent_runs=1)
        self.make_run(task_status="in_progress")
        stopped = self.make_run(task_status="completed")

        response = self.send(stopped)

        assert (response.status_code, response.json()["code"]) == (429, "concurrency_limited")
        assert self.tasks.resume_calls == []


class TestCancelRun(RunsAPITestCase):
    @parameterized.expand(
        [
            ("accepted", 202),
            ("already_terminal", 200),
            ("unavailable", 503),
            ("not_cloud", 503),
            ("not_found", 404),
        ]
    )
    def test_cancel_outcome_of_an_active_run(self, outcome: str, http_status: int) -> None:
        run = self.make_run(task_status="in_progress")
        self.mocks["runs.cancel_task_run"].return_value = (outcome, None)

        response = self.client.post(self.runs_url(f"{run.id}/cancel/"))

        assert response.status_code == http_status, response.json()
        if http_status == 503:
            assert (response.json()["code"], response.headers["Retry-After"]) == ("cancel_unavailable", "5")
        args, kwargs = self.mocks["runs.cancel_task_run"].call_args
        assert args == (self.tasks.current_run_id(run), run.task_id, self.team.id)
        assert (kwargs["source"], kwargs["requested_by_user_id"]) == ("cloud_agents_api", self.user.id)

    @parameterized.expand(
        [
            ("idle", "completed", {}, "idle", "turn_closed"),
            ("idle_after_a_failure", "failed", {}, "idle", "unexpected_failure"),
            ("done", "cancelled", {"cancel_source": "cloud_agents_api"}, "done", "cancelled"),
        ]
    )
    def test_cancel_of_a_run_with_no_agent_at_work_changes_nothing(
        self, _name: str, task_status: str, state: dict[str, Any], run_status: str, reason: str
    ) -> None:
        run = self.make_run(task_status="in_progress")
        self.tasks.set_status(self.tasks.current_run_id(run), task_status, state=state)

        response = self.client.post(self.runs_url(f"{run.id}/cancel/"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["status"], response.json()["status_reason"]) == (run_status, reason)
        self.mocks["runs.cancel_task_run"].assert_not_called()

    def test_task_that_tasks_does_not_hold_for_this_product_is_never_cancelled(self) -> None:
        run = self.make_run(task_id=uuid4())
        response = self.client.post(self.runs_url(f"{run.id}/cancel/"))
        assert (response.status_code, response.json()["code"]) == (status.HTTP_409_CONFLICT, "run_not_ready")
        self.mocks["runs.cancel_task_run"].assert_not_called()


class TestRunStatus(RunsAPITestCase):
    def read(self, run: CloudAgentRun) -> dict[str, Any]:
        return self.client.get(self.runs_url(f"{run.id}/")).json()

    @parameterized.expand(
        [
            ("turn_closed", "completed", {}, None, "idle", "turn_closed", False),
            ("pr_open", "completed", {}, {"pr_url": PR_URL, "pr_state": "open"}, "idle", "turn_closed", False),
            ("pr_merged", "completed", {}, {"pr_url": PR_URL, "pr_state": "merged"}, "done", "finished", True),
            ("pr_closed", "completed", {}, {"pr_url": PR_URL, "pr_state": "closed"}, "done", "closed", True),
            (
                "infrastructure_failure",
                "failed",
                {"compute_waived_reason": "SandboxProvisionError"},
                None,
                "idle",
                "provision_failed",
                True,
            ),
            ("timeout", "failed", {"timed_out_inactivity": True}, None, "idle", "timed_out", True),
            (
                "quota_sweep",
                "cancelled",
                {"cancel_source": QUOTA_SWEEP_CANCEL_SOURCE},
                None,
                "idle",
                "credit_spent",
                True,
            ),
            ("user_cancel", "cancelled", {"cancel_source": "cloud_agents_api"}, None, "done", "cancelled", False),
        ]
    )
    def test_ended_run_reads_as_idle_or_done(
        self,
        _name: str,
        task_status: str,
        state: dict[str, Any],
        output: dict[str, Any] | None,
        run_status: str,
        reason: str,
        has_detail: bool,
    ) -> None:
        run = self.make_run(task_status="in_progress")
        self.tasks.set_status(self.tasks.current_run_id(run), task_status, state=state, output=output)

        body = self.read(run)
        message = self.client.post(self.runs_url(f"{run.id}/messages/"), data={"content": "Go on"}, format="json")

        assert (body["status"], body["status_reason"]) == (run_status, reason)
        assert (body["status_detail"] is not None) is has_detail
        assert body["ended_at"] is not None
        if run_status == "done":
            assert (message.status_code, message.json()["code"]) == (status.HTTP_409_CONFLICT, "run_done")
            assert self.tasks.resume_calls == []
        else:
            assert (message.status_code, message.json()["resumed"]) == (status.HTTP_202_ACCEPTED, True)

    def test_done_run_refuses_a_message_before_the_quota_check(self) -> None:
        run = self.make_run(task_status="cancelled")
        self.mocks["runs.cloud_agents_quota_denial"].return_value = "quota_exhausted"
        response = self.client.post(self.runs_url(f"{run.id}/messages/"), data={"content": "Go on"}, format="json")
        assert (response.status_code, response.json()["code"]) == (status.HTTP_409_CONFLICT, "run_done")

    @parameterized.expand(
        [
            ("with_schema", ANSWER_SCHEMA, {"answer": "42", "pr_url": PR_URL}, {"answer": "42"}),
            ("with_schema_and_no_result_yet", ANSWER_SCHEMA, {"pr_url": PR_URL}, None),
            ("without_schema", None, {"answer": "42"}, None),
        ]
    )
    def test_structured_result(
        self, _name: str, schema: dict[str, Any] | None, output: dict[str, Any], expected: dict[str, Any] | None
    ) -> None:
        run = self.make_run(task_status="in_progress", config={**RUN_CONFIG, "output_schema": schema})
        self.tasks.set_status(self.tasks.current_run_id(run), "completed", output=output)

        body = self.read(run)

        assert body["result"]["output"] == expected
        assert body["config"]["output_schema"] == schema
