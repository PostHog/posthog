from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.intercom.template_intercom import template as template_intercom, TemplateIntercomMigrator
from posthog.models.plugin import PluginConfig
from posthog.test.base import BaseTest


class TestTemplateIntercom(BaseHogFunctionTemplateTest):
    template = template_intercom

    def _inputs(self, **kwargs):
        inputs = {
            "access_token": "TOKEN",
            "email": "example@posthog.com",
            "host": "api.intercom.com",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"status": "success"}}  # type: ignore

        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.get_mock_fetch_calls() == [
            (
                "https://api.intercom.com/events",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer TOKEN",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    "body": {
                        "event_name": "event-name",
                        "created_at": 1704067200,
                        "email": "example@posthog.com",
                        "id": "distinct-id",
                    },
                },
            )
        ]
        assert self.get_mock_print_calls() == [("Event sent successfully!",)]

    def test_exits_if_no_email(self):
        for email in [None, ""]:
            self.mock_print.reset_mock()
            res = self.run_function(inputs=self._inputs(email=email))

            assert res.result is None
            assert self.get_mock_fetch_calls() == []
            assert self.get_mock_print_calls() == [("`email` input is empty. Skipping.",)]

    def test_logs_missing_error(self):
        self.mock_fetch_response = lambda *args: {"status": 404, "body": {"status": "missing"}}  # type: ignore
        self.run_function(inputs=self._inputs())
        assert self.get_mock_print_calls() == [("No existing contact found for email",)]

    def test_logs_other_errors(self):
        self.mock_fetch_response = lambda *args: {  # type: ignore
            "status": 400,
            "body": {
                "type": "error.list",
                "request_id": "001dh0h1qb205el244gg",
                "errors": [{"code": "error", "message": "Other error"}],
            },
        }
        self.run_function(inputs=self._inputs())
        assert self.get_mock_print_calls() == [
            (
                "Error sending event:",
                400,
                {
                    "type": "error.list",
                    "request_id": "001dh0h1qb205el244gg",
                    "errors": [{"code": "error", "message": "Other error"}],
                },
            )
        ]


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "intercomApiKey": "INTERCOM_API_KEY",
            "triggeringEvents": "$identify",
            "ignoredEmailDomains": "",
            "useEuropeanDataStorage": "No",
        }

        _config.update(config)
        return PluginConfig(enabled=True, order=0, config=_config)

    def test_full_function(self):
        obj = self.get_plugin_config({})

        template = TemplateIntercomMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "access_token": {"value": "INTERCOM_API_KEY"},
                "host": {"value": "api.intercom.io"},
                "email": {"value": "{person.properties.email}"},
            }
        )
        assert template["filters"] == snapshot(
            {"events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}]}
        )

    def test_eu_host(self):
        obj = self.get_plugin_config(
            {
                "useEuropeanDataStorage": "Yes",
            }
        )

        template = TemplateIntercomMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "access_token": {"value": "INTERCOM_API_KEY"},
                "host": {"value": "api.eu.intercom.com"},
                "email": {"value": "{person.properties.email}"},
            }
        )

    def test_triggering_events(self):
        obj = self.get_plugin_config(
            {
                "triggeringEvents": "$identify,$pageview, custom event, ",
            }
        )

        template = TemplateIntercomMigrator.migrate(obj)
        assert template["filters"] == snapshot(
            {
                "events": [
                    {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
                    {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                    {"id": "custom event", "name": "custom event", "type": "events", "order": 0},
                ]
            }
        )

    def test_ignore_domains(self):
        obj = self.get_plugin_config(
            {
                "ignoredEmailDomains": "test.com, other-com, ",
            }
        )

        template = TemplateIntercomMigrator.migrate(obj)
        assert template["filters"] == snapshot(
            {
                "properties": [
                    {"key": "email", "value": "test.com", "operator": "not_icontains", "type": "person"},
                    {"key": "email", "value": " other-com", "operator": "not_icontains", "type": "person"},
                    {"key": "email", "value": " ", "operator": "not_icontains", "type": "person"},
                ],
                "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
            }
        )
