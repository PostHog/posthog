from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.hubspot.template_hubspot import template as template_hubspot, TemplateHubspotMigrator
from posthog.models import PluginConfig
from posthog.test.base import BaseTest


class TestTemplateHubspot(BaseHogFunctionTemplateTest):
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
                "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {
                        "inputs": [
                            {
                                "properties": {"company": "PostHog", "email": "example@posthog.com"},
                                "id": "example@posthog.com",
                                "idProperty": "email",
                            }
                        ]
                    },
                },
            )
        ]
        assert self.get_mock_print_calls() == [("Contact example@posthog.com updated successfully!",)]

    def test_exits_if_no_email(self):
        for email in [None, ""]:
            self.mock_print.reset_mock()
            res = self.run_function(inputs=self._inputs(email=email))

            assert res.result is None
            assert self.get_mock_fetch_calls() == []
            assert self.get_mock_print_calls() == [("`email` input is empty. Not creating a contact.",)]


class TestTemplateMigration(BaseTest):
    def get_plugin_config(self, config: dict):
        _config = {
            "hubspotAccessToken": "toky",
            "triggeringEvents": "$identify,$set",
            "additionalPropertyMappings": "a:b",
            "ignoredEmails": "gmail.com",
        }
        _config.update(config)
        return PluginConfig(enabled=True, order=0, config=_config)

    def test_default_config(self):
        obj = self.get_plugin_config({})
        template = TemplateHubspotMigrator.migrate(obj)
        assert template["inputs"] == snapshot(
            {
                "access_token": {"value": "toky"},
                "email": {"value": "{person.properties.email}"},
                "properties": {
                    "value": {
                        "firstname": "{person.properties.firstname ?? person.properties.firstName ?? person.properties.first_name}",
                        "lastname": "{person.properties.lastname ?? person.properties.lastName ?? person.properties.last_name}",
                        "company": "{person.properties.company ?? person.properties.companyName ?? person.properties.company_name}",
                        "phone": "{person.properties.phone ?? person.properties.phoneNumber ?? person.properties.phone_number}",
                        "website": "{person.properties.website ?? person.properties.companyWebsite ?? person.properties.company_website}",
                        "b": "{person.properties.a}",
                    }
                },
            }
        )
        assert template["filters"] == {
            "properties": [{"key": "email", "value": "gmail.com", "operator": "not_icontains", "type": "person"}],
            "events": [
                {"id": "$identify", "name": "$identify", "type": "events", "properties": []},
                {"id": "$set", "name": "$set", "type": "events", "properties": []},
            ],
        }
        assert template["inputs_schema"][0]["key"] == "access_token"
        assert template["inputs_schema"][0]["type"] == "string"
        assert template["inputs_schema"][0]["secret"]
        assert "inputs.oauth.access_token" not in template["hog"]
        assert "inputs.access_token" in template["hog"]
