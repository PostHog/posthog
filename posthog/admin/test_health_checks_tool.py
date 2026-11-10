import re
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.messages import get_messages

from parameterized import parameterized
from structlog.testing import capture_logs
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.admin.console.health_checks_tool import HealthCheckRun, HealthCheckRuns
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded

TOOL_URL = "/admin/console/tools/health-checks/"


def _run(status: str) -> HealthCheckRun:
    return HealthCheckRun(
        workflow_id="health-check-example-manual-1",
        run_id="run-1",
        status=status,
        started=datetime(2026, 11, 5, 12, 0, tzinfo=UTC),
        closed=None if status == "RUNNING" else datetime(2026, 11, 5, 12, 5, tzinfo=UTC),
    )


class TestHealthChecksTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        ensure_registry_loaded()
        self.check = sorted(HEALTH_CHECKS.values(), key=lambda check: check.name)[0]
        self.check_url = f"{TOOL_URL}?check={self.check.kind}"

    @parameterized.expand(
        [
            ("running", [_run("RUNNING")], "", True),
            ("finished", [_run("COMPLETED")], "", False),
            ("continued_as_new_and_closed", [_run("CONTINUED_AS_NEW")], "", False),
            ("started_run_not_listed_yet", [], "&started=health-check-example-manual-2", True),
            ("started_run_listed_and_finished", [_run("COMPLETED")], "&started=health-check-example-manual-1", False),
            ("temporal_away", None, "", True),
        ]
    )
    def test_the_runs_refresh_only_while_there_is_something_to_wait_for(
        self, _name: str, runs: list[HealthCheckRun] | None, extra_query: str, refreshes: bool
    ) -> None:
        with patch.object(HealthCheckRuns, "recent", return_value=runs):
            page = self.client.get(self.check_url + extra_query).content.decode()
            live = self.client.get(f"{TOOL_URL}live/runs/?check={self.check.kind}{extra_query}")

        assert f"/admin/console/tools/health-checks/run/?check={self.check.kind}" in page
        assert f'data-console-live="{TOOL_URL}live/runs/?check={self.check.kind}' in page
        assert live.status_code == 200
        assert live["X-Console-Live"] == "1"
        assert ("data-refresh-seconds" in live.content.decode()) == refreshes

    # Mocks the connection one level down, so the real sync_connect wrapper runs: it refuses to run inside an
    # event loop, which a mock of sync_connect itself would hide.
    @patch("posthog.temporal.common.client.connect")
    def test_the_runs_come_from_temporal(self, connect: AsyncMock) -> None:
        workflow = MagicMock(id="health-check-example-manual-1", run_id="run-1", start_time=None, close_time=None)
        workflow.status.name = "RUNNING"

        timeouts = []

        async def list_workflows(query: str, limit: int | None = None, rpc_timeout: timedelta | None = None):
            timeouts.append(rpc_timeout)
            yield workflow

        connect.return_value = MagicMock(list_workflows=list_workflows)

        content = self.client.get(f"{TOOL_URL}live/runs/?check={self.check.kind}").content.decode()

        assert "health-check-example-manual-1" in content
        assert "data-refresh-seconds" in content
        assert timeouts and all(timeout is not None for timeout in timeouts)

    @patch("posthog.admin.console.health_checks_tool.sync_connect")
    def test_a_double_submitted_run_form_starts_one_workflow(self, sync_connect: MagicMock) -> None:
        start_workflow = AsyncMock(side_effect=[None, WorkflowAlreadyStartedError("id", "health-check-workflow")])
        sync_connect.return_value.start_workflow = start_workflow
        form = self.client.get(f"{TOOL_URL}run/?check={self.check.kind}").content.decode()
        nonce = re.search(r'name="form_nonce" value="([^"]+)"', form)
        assert nonce is not None
        data = {"batch_size": 10, "max_concurrent": 1, "rollout_percentage": 1.0, "form_nonce": nonce.group(1)}

        with capture_logs() as logs:
            responses = [self.client.post(f"{TOOL_URL}run/?check={self.check.kind}", data) for _ in range(2)]

        started = next(log for log in logs if log["event"] == "admin_console_operation_started")
        assert started["query"] == {"check": self.check.kind}
        assert [response.status_code for response in responses] == [302, 302]
        assert (
            responses[0]["Location"]
            == f"{self.check_url}&started=health-check-{self.check.name}-manual-{nonce.group(1)}"
        )
        workflow_ids = {call.kwargs["id"] for call in start_workflow.call_args_list}
        assert workflow_ids == {f"health-check-{self.check.name}-manual-{nonce.group(1)}"}
        assert {call.kwargs["id_reuse_policy"] for call in start_workflow.call_args_list} == {
            WorkflowIDReusePolicy.REJECT_DUPLICATE
        }
        levels = [message.level_tag for message in get_messages(responses[1].wsgi_request)]
        assert "info" in levels

    def test_an_old_health_check_url_keeps_its_check_and_parameters(self) -> None:
        response = self.client.get(f"/admin/health-checks/{self.check.kind}/?from=bookmark")

        assert response.status_code == 302
        assert response["Location"] == f"{self.check_url}&from=bookmark"
