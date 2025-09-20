from datetime import datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from inline_snapshot import snapshot

from posthog.cdp.templates.google_cloud_storage.template_google_cloud_storage import TemplateGoogleCloudStorageMigrator
from posthog.models import Integration, Plugin, PluginAttachment, PluginConfig


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "bucketName": "BUCKET_NAME",
            "exportEventsToIgnore": "",
        }
        _config.update(config)
        return PluginConfig(enabled=True, order=0, config=_config)

    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    def test_integration(self, mock_credentials):
        mock_credentials.return_value.project_id = "posthog-616"
        mock_credentials.return_value.service_account_email = "posthog@"
        mock_credentials.return_value.token = "ACCESS_TOKEN"
        mock_credentials.return_value.expiry = datetime.fromtimestamp(1704110400 + 3600)
        mock_credentials.return_value.refresh = lambda _: None

        plugin = Plugin()
        plugin.save()
        obj = self.get_plugin_config({})
        obj.plugin = plugin
        obj.team = self.team
        obj.save()
        PluginAttachment.objects.create(
            plugin_config=obj, contents=b'{"cloud": "key"}', key="googleCloudKeyJson", file_size=10
        )

        template = TemplateGoogleCloudStorageMigrator.migrate(obj)
        template["inputs"]["auth"]["value"] = 1  # mock the ID
        assert template["inputs"] == snapshot(
            {
                "auth": {"value": 1},
                "bucketName": {"value": "BUCKET_NAME"},
                "payload": {
                    "value": "uuid,event,properties,elements,people_set,people_set_once,distinct_id,team_id,ip,site_url,timestamp\n"
                    + "{event.uuid},{event.event},{jsonStringify(event.properties)},{event.elements_chain},{jsonStringify(event.properties.$set)},{jsonStringify(event.properties.$set_once)},{event.distinct_id},,,,{event.timestamp}"
                },
                "filename": {
                    "value": "{toDate(event.timestamp)}/{replaceAll(replaceAll(replaceAll(toString(event.timestamp), '-', ''), ':', ''), 'T', '-')}-{event.uuid}.csv"
                },
            }
        )
        assert template["filters"] == {}

        integration = Integration.objects.last()
        assert integration is not None
        assert integration.kind == "google-cloud-storage"
        assert integration.sensitive_config == {"cloud": "key"}
        assert integration.config.get("access_token") == "ACCESS_TOKEN"

    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    def test_ignore_events(self, mock_credentials):
        mock_credentials.return_value.project_id = "posthog-616"
        mock_credentials.return_value.service_account_email = "posthog@"
        mock_credentials.return_value.token = "ACCESS_TOKEN"
        mock_credentials.return_value.expiry = datetime.fromtimestamp(1704110400 + 3600)
        mock_credentials.return_value.refresh = lambda _: None

        plugin = Plugin()
        plugin.save()
        obj = self.get_plugin_config(
            {
                "exportEventsToIgnore": "event1, event2",
            }
        )
        obj.plugin = plugin
        obj.team = self.team
        obj.save()
        PluginAttachment.objects.create(
            plugin_config=obj, contents=b'{"cloud": "key"}', key="googleCloudKeyJson", file_size=10
        )

        template = TemplateGoogleCloudStorageMigrator.migrate(obj)
        template["inputs"]["auth"]["value"] = 1  # mock the ID
        assert template["inputs"] == snapshot(
            {
                "auth": {"value": 1},
                "bucketName": {"value": "BUCKET_NAME"},
                "payload": {
                    "value": "uuid,event,properties,elements,people_set,people_set_once,distinct_id,team_id,ip,site_url,timestamp\n"
                    + "{event.uuid},{event.event},{jsonStringify(event.properties)},{event.elements_chain},{jsonStringify(event.properties.$set)},{jsonStringify(event.properties.$set_once)},{event.distinct_id},,,,{event.timestamp}"
                },
                "filename": {
                    "value": "{toDate(event.timestamp)}/{replaceAll(replaceAll(replaceAll(toString(event.timestamp), '-', ''), ':', ''), 'T', '-')}-{event.uuid}.csv"
                },
            }
        )
        assert template["filters"] == snapshot(
            {
                "events": [
                    {
                        "id": None,
                        "name": "All events",
                        "type": "events",
                        "order": 0,
                        "properties": [{"key": "event not in ('event1', 'event2')", "type": "hogql"}],
                    }
                ]
            }
        )
