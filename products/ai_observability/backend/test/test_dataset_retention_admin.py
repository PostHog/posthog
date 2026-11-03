from posthog.test.base import BaseTest

from django.urls import reverse

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config

from products.ai_observability.backend.dataset_retention import RETENTION_ENABLED_SETTING, dataset_retention_enabled


class TestDatasetRetentionAdmin(BaseTest):
    @parameterized.expand([("enabled", True), ("disabled", False)])
    def test_staff_can_change_cleanup_setting(self, value: str, expected: bool) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)
        url = reverse("admin:ai-observability-dataset-retention")
        with override_instance_config(RETENTION_ENABLED_SETTING, not expected):
            response = self.client.get(url)
            self.assertContains(response, "AI observability dataset retention")
            self.assertEqual(dataset_retention_enabled(), not expected)
            response = self.client.post(url, {"enabled": value}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(dataset_retention_enabled(), expected)

    def test_nonstaff_cannot_change_cleanup_setting(self) -> None:
        self.client.force_login(self.user)
        with override_instance_config(RETENTION_ENABLED_SETTING, True):
            response = self.client.post(reverse("admin:ai-observability-dataset-retention"), {"enabled": "disabled"})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(dataset_retention_enabled())

    def test_invalid_setting_does_not_disable_cleanup(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)
        with override_instance_config(RETENTION_ENABLED_SETTING, True):
            response = self.client.post(reverse("admin:ai-observability-dataset-retention"), {"enabled": "invalid"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(dataset_retention_enabled())
