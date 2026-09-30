from typing import Any

from posthog.test.base import TestMigrations

ALERT_FILTERS = {
    "source": "internal-events",
    "events": [{"id": "$logs_alert_firing", "type": "events"}],
    "properties": [{"key": "alert_id", "value": "alert-1", "operator": "exact", "type": "event"}],
}
LEAKED_NAME = "Logs — Errors (firing) → Webhook https://hooks.example.com/services/T000/B000/s3cr3t"
LEAKED_SEGMENT = LEAKED_NAME.replace("/", "\\/")
REDACTED_NAME = "Logs — Errors (firing) → Webhook hooks.example.com"


class TestRedactWebhookUrlsInDestinationNames(TestMigrations):
    app = "alerts"
    migrate_from = "0008_platformalert_firing_started_at_and_uuid7_pk"
    migrate_to = "0009_redact_webhook_urls_in_destination_names"

    def setUpBeforeMigration(self, apps: Any) -> None:
        HogFunction = apps.get_model("cdp", "HogFunction")
        FileSystem = apps.get_model("posthog", "FileSystem")
        FileSystemShortcut = apps.get_model("posthog", "FileSystemShortcut")

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
            path="Unfiled/Destinations/" + LEAKED_SEGMENT,
            depth=3,
            type="hog_function/internal_destination",
            ref=str(self.alert_webhook.id),
        )
        self.shortcut = FileSystemShortcut.objects.create(
            team_id=self.team.id,
            user_id=self.user.id,
            path=LEAKED_SEGMENT,
            type="hog_function/internal_destination",
            ref=str(self.alert_webhook.id),
        )
        self.user_webhook_name = "My webhook https://hooks.example.com/services/T000/B000/mine"
        self.user_webhook = make(self.user_webhook_name, {"source": "internal-events", "events": []})

        self.quoted_webhook = make(
            "Logs — Errors (firing) → Webhook https://hooks.example.com/hook?token='s3cr3t",
            ALERT_FILTERS,
        )
        self.quoted_in_alert_name = make(
            "Logs — https://hooks.example.com/h?t='s3cr3t (firing) → Webhook https://hooks.example.com/other",
            ALERT_FILTERS,
        )

    def test_only_alert_managed_webhook_names_are_redacted(self) -> None:
        assert self.apps is not None
        HogFunction = self.apps.get_model("cdp", "HogFunction")
        FileSystem = self.apps.get_model("posthog", "FileSystem")
        FileSystemShortcut = self.apps.get_model("posthog", "FileSystemShortcut")

        assert HogFunction.objects.get(id=self.alert_webhook.id).name == REDACTED_NAME
        assert FileSystem.objects.get(id=self.file_entry.id).path == "Unfiled/Destinations/" + REDACTED_NAME
        # A starred destination keeps its own copy of the name.
        assert FileSystemShortcut.objects.get(id=self.shortcut.id).path == REDACTED_NAME
        assert HogFunction.objects.get(id=self.user_webhook.id).name == self.user_webhook_name
        # An apostrophe is legal in a URL query, and treating it as the end of the URL used to
        # leave everything after it in the name. That holds for the URL the builder appended and
        # for one the alert's own name carried, which has text after it.
        assert HogFunction.objects.get(id=self.quoted_webhook.id).name == REDACTED_NAME
        assert (
            HogFunction.objects.get(id=self.quoted_in_alert_name.id).name
            == "Logs — hooks.example.com (firing) → Webhook hooks.example.com"
        )
