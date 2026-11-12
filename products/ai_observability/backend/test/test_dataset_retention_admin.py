from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config

from products.ai_observability.backend.dataset_retention import RETENTION_ENABLED_SETTING, dataset_retention_enabled

TOOL_URL = "/admin/console/tools/ai-observability/"


class TestDatasetRetentionConsoleTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)

    @parameterized.expand(
        [
            ("pause", True, "pause-dataset-cleanup", {}, 302, False),
            ("resume", False, "resume-dataset-cleanup", {"reason": "The incident is over"}, 302, True),
            ("resume_without_a_reason", False, "resume-dataset-cleanup", {"reason": " "}, 400, False),
            ("pause_when_already_paused", False, "pause-dataset-cleanup", {}, 404, False),
        ]
    )
    def test_staff_pause_or_resume_cleanup_from_the_tool(
        self,
        _name: str,
        enabled_before: bool,
        operation_key: str,
        data: dict[str, str],
        expected_status: int,
        enabled_after: bool,
    ) -> None:
        with override_instance_config(RETENTION_ENABLED_SETTING, enabled_before):
            response = self.client.post(f"{TOOL_URL}{operation_key}/", data)

            assert response.status_code == expected_status
            assert dataset_retention_enabled() == enabled_after

    @parameterized.expand(
        [
            ("dataset_retention", "/admin/posthog/organization/ai-observability-dataset-retention/"),
            ("usage_report", "/admin/posthog/organization/send-ai-observability-usage-report/?date=2026-07-15"),
        ]
    )
    def test_the_old_admin_pages_open_the_tool(self, _name: str, old_url: str) -> None:
        with override_instance_config(RETENTION_ENABLED_SETTING, True):
            response = self.client.get(old_url, follow=True)

        query = old_url.partition("?")[2]
        assert response.redirect_chain == [(TOOL_URL + (f"?{query}" if query else ""), 302)]
        assert "Dataset cleanup is on in this region." in response.content.decode()
