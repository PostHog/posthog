from datetime import datetime
from unittest.mock import patch

from inline_snapshot import snapshot

from posthog.cdp.templates.google_pubsub.template_google_pubsub import TemplateGooglePubSubMigrator
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.hubspot.template_hubspot import template as template_hubspot
from posthog.models import PluginConfig, PluginAttachment, Plugin, Integration
from posthog.test.base import BaseTest


class TestTemplateGooglePubSub(BaseHogFunctionTemplateTest):
    template = template_hubspot

    def _inputs(self, **kwargs):
        inputs = {
            "oauth": {"access_token": "TOKEN"},
            "email": "example@posthog.com",
            "properties": {
                "company": "PostHog",
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"status": "success"}}  # type: ignore

        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.get_mock_fetch_calls() == [
            (
                "https://api.hubapi.com/crm/v3/objects/contacts",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {"properties": {"company": "PostHog", "email": "example@posthog.com"}},
                },
            )
        ]
        assert self.get_mock_print_calls() == [("Contact created successfully!",)]

    def test_exits_if_no_email(self):
        for email in [None, ""]:
            self.mock_print.reset_mock()
            res = self.run_function(inputs=self._inputs(email=email))

            assert res.result is None
            assert self.get_mock_fetch_calls() == []
            assert self.get_mock_print_calls() == [("`email` input is empty. Not creating a contact.",)]

    def test_handles_updates(self):
        call_count = 0

        # First call respond with 409, second one 200 and increment call_count
        def mock_fetch(*args):
            nonlocal call_count
            call_count += 1
            return (
                {"status": 409, "body": {"message": "Contact already exists. Existing ID: 12345"}}
                if call_count == 1
                else {"status": 200, "body": {"status": "success"}}
            )

        self.mock_fetch_response = mock_fetch  # type: ignore

        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert len(self.get_mock_fetch_calls()) == 2

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.hubapi.com/crm/v3/objects/contacts",
            {
                "method": "POST",
                "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                "body": {"properties": {"company": "PostHog", "email": "example@posthog.com"}},
            },
        )

        assert self.get_mock_fetch_calls()[1] == (
            "https://api.hubapi.com/crm/v3/objects/contacts/12345",
            {
                "method": "PATCH",
                "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                "body": {"properties": {"company": "PostHog", "email": "example@posthog.com"}},
            },
        )


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "topicId": "TOPIC_ID",
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

        template = TemplateGooglePubSubMigrator.migrate(obj)
        template["inputs"]["auth"]["value"] = 1  # mock the ID
        assert template["inputs"] == snapshot(
            {
                "auth": {"value": 1},
                "topicId": {"value": "TOPIC_ID"},
                "payload": {
                    "value": {
                        "event": "{event.event}",
                        "distinct_id": "{event.distinct_id}",
                        "team_id": "{event.team_id}",
                        "ip": "{event.ip}",
                        "site_url": "{event.site_url}",
                        "timestamp": "{event.timestamp}",
                        "uuid": "{event.uuid}",
                        "properties": "{event.properties}",
                        "elements": [],
                        "people_set": "{person.properties}",
                        "people_set_once": {},
                    }
                },
                "attributes": {"value": {}},
            }
        )
        assert template["filters"] == {}

        integration = Integration.objects.last()
        assert integration.kind == "gc-pubsub"
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

        template = TemplateGooglePubSubMigrator.migrate(obj)
        template["inputs"]["auth"]["value"] = 1  # mock the ID
        assert template["inputs"] == snapshot(
            {
                "auth": {"value": 1},
                "topicId": {"value": "TOPIC_ID"},
                "payload": {
                    "value": {
                        "event": "{event.event}",
                        "distinct_id": "{event.distinct_id}",
                        "team_id": "{event.team_id}",
                        "ip": "{event.ip}",
                        "site_url": "{event.site_url}",
                        "timestamp": "{event.timestamp}",
                        "uuid": "{event.uuid}",
                        "properties": "{event.properties}",
                        "elements": [],
                        "people_set": "{person.properties}",
                        "people_set_once": {},
                    }
                },
                "attributes": {"value": {}},
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
