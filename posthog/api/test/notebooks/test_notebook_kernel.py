from posthog.test.base import APIBaseTest

from products.notebooks.backend.kernel import notebook_kernel_service
from products.notebooks.backend.models import Notebook


class TestNotebookKernels(APIBaseTest):
    def tearDown(self):
        notebook_kernel_service.shutdown_all()
        return super().tearDown()

    def test_kernel_can_be_started_and_reused(self):
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)

        start_one = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/start",
            format="json",
        )
        start_two = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/start",
            format="json",
        )

        assert start_one.status_code == 200
        assert start_two.status_code == 200
        assert start_one.json()["id"] == start_two.json()["id"]
        assert start_two.json()["alive"] is True

    def test_kernel_can_execute_python_and_return_variables(self):
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)

        execute = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/execute",
            data={"code": "value = 2 + 3\nvalue"},
            format="json",
        )

        assert execute.status_code == 200

        payload = execute.json()

        assert payload["status"] == "ok"
        assert payload["result"]["text/plain"] == "5"
        assert payload["variables"]["value"] == "5"
        assert payload["kernel"]["alive"] is True

    def test_kernel_can_be_stopped_and_restarted(self):
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)

        started = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/start",
            format="json",
        )
        stopped = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/stop",
            format="json",
        )
        restarted = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/start",
            format="json",
        )

        assert started.status_code == 200
        assert stopped.status_code == 200
        assert restarted.status_code == 200
        assert stopped.json() == {"stopped": True}
        assert started.json()["id"] != restarted.json()["id"]

    def test_scratchpad_kernel_can_execute_without_notebook(self):
        execute = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/scratchpad/kernel/execute",
            data={"code": "2 + 2"},
            format="json",
        )

        assert execute.status_code == 200

        payload = execute.json()

        assert payload["status"] == "ok"
        assert payload["result"]["text/plain"] == "4"
        assert payload["kernel"]["notebook_short_id"] == "scratchpad"
        assert Notebook.objects.filter(short_id="scratchpad").exists() is False
