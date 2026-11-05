import re
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.messages import get_messages

from parameterized import parameterized
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

    @parameterized.expand([("running", "RUNNING", True), ("finished", "COMPLETED", False)])
    def test_the_runs_refresh_only_while_a_run_is_going(self, _name: str, status: str, refreshes: bool) -> None:
        with patch.object(HealthCheckRuns, "recent", return_value=[_run(status)]):
            page = self.client.get(self.check_url).content.decode()
            live = self.client.get(f"{TOOL_URL}live/runs/?check={self.check.kind}")

        assert f"/admin/console/tools/health-checks/run/?check={self.check.kind}" in page
        assert f'data-console-live="{TOOL_URL}live/runs/?check={self.check.kind}"' in page
        assert live.status_code == 200
        assert live["X-Console-Live"] == "1"
        content = live.content.decode()
        assert "health-check-example-manual-1" in content
        assert ("data-refresh-seconds" in content) == refreshes

    @patch("posthog.admin.console.health_checks_tool.sync_connect")
    def test_a_double_submitted_run_form_starts_one_workflow(self, sync_connect: MagicMock) -> None:
        start_workflow = AsyncMock(side_effect=[None, WorkflowAlreadyStartedError("id", "health-check-workflow")])
        sync_connect.return_value.start_workflow = start_workflow
        form = self.client.get(f"{TOOL_URL}run/?check={self.check.kind}").content.decode()
        nonce = re.search(r'name="form_nonce" value="([^"]+)"', form)
        assert nonce is not None
        data = {"batch_size": 10, "max_concurrent": 1, "rollout_percentage": 1.0, "form_nonce": nonce.group(1)}

        responses = [self.client.post(f"{TOOL_URL}run/?check={self.check.kind}", data) for _ in range(2)]

        assert [response.status_code for response in responses] == [302, 302]
        assert responses[0]["Location"] == self.check_url
        workflow_ids = {call.kwargs["id"] for call in start_workflow.call_args_list}
        assert workflow_ids == {f"health-check-{self.check.name}-manual-{nonce.group(1)}"}
        levels = [message.level_tag for message in get_messages(responses[1].wsgi_request)]
        assert "info" in levels

    def test_an_old_health_check_url_keeps_its_check_and_parameters(self) -> None:
        response = self.client.get(f"/admin/health-checks/{self.check.kind}/?from=bookmark")

        assert response.status_code == 302
        assert response["Location"] == f"{self.check_url}&from=bookmark"
