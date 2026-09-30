from typing import Any

from posthog.test.base import TestMigrations

ALERT_FILTERS = {
    "source": "internal-events",
    "events": [{"id": "$logs_alert_firing", "type": "events"}],
    "properties": [{"key": "alert_id", "value": "alert-1", "operator": "exact", "type": "event"}],
}
LEAKED_NAME = "Logs — Errors (firing) → Webhook https://hooks.example.com/services/T000/B000/s3cr3t"


class TestRedactWebhookUrlsInDestinationNames(TestMigrations):
    app = "alerts"
    migrate_from = "0008_platformalert_firing_started_at_and_uuid7_pk"
    migrate_to = "0009_redact_webhook_urls_in_destination_names"

    def setUpBeforeMigration(self, apps: Any) -> None:
        HogFunction = apps.get_model("cdp", "HogFunction")
        FileSystem = apps.get_model("posthog", "FileSystem")

        def make(name: str, filters: dict) -> Any:
            return HogFunction.objects.create(
                team_id=self.team.id,
                type="internal_destination",
                template_id="template-webhook",
                name=name,
                filters=filters,
                hog="return",
            )

        self.alert_webhook = make(LEAKED_NAME, ALERT_FILTERS)
        self.file_entry = FileSystem.objects.create(
            team_id=self.team.id,
            path="Unfiled/Destinations/" + LEAKED_NAME.replace("/", "\\/"),
            depth=3,
            type="hog_function/internal_destination",
            ref=str(self.alert_webhook.id),
        )
        self.user_webhook_name = "My webhook https://hooks.example.com/services/T000/B000/mine"
        self.user_webhook = make(self.user_webhook_name, {"source": "internal-events", "events": []})

    def test_only_alert_managed_webhook_names_are_redacted(self) -> None:
        assert self.apps is not None
        HogFunction = self.apps.get_model("cdp", "HogFunction")
        FileSystem = self.apps.get_model("posthog", "FileSystem")

        assert (
            HogFunction.objects.get(id=self.alert_webhook.id).name
            == "Logs — Errors (firing) → Webhook hooks.example.com"
        )
        assert (
            FileSystem.objects.get(id=self.file_entry.id).path
            == "Unfiled/Destinations/Logs — Errors (firing) → Webhook hooks.example.com"
        )
        assert HogFunction.objects.get(id=self.user_webhook.id).name == self.user_webhook_name
