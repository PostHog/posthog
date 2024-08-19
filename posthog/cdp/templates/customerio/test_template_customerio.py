from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.customerio.template_customerio import template as template_customerio


def create_inputs(**kwargs):
    inputs = {
        "site_id": "SITE_ID",
        "token": "TOKEN",
        "host": "track.customer.io",
        "action": "automatic",
        "include_all_properties": False,
        "identifiers": {"email": "example@posthog.com"},
        "attributes": {"name": "example"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateCustomerio(BaseHogFunctionTemplateTest):
    template = template_customerio

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"name": "$pageview", "properties": {"url": "https://example.com"}},
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://track.customer.io/api/v2/entity",
                {
                    "method": "POST",
                    "headers": {
                        "User-Agent": "PostHog Customer.io App",
                        "Authorization": "Basic U0lURV9JRDpUT0tFTg==",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "type": "person",
                        "action": "page",
                        "name": None,
                        "identifiers": {"email": "example@posthog.com"},
                        "attributes": {"name": "example"},
                        "timestamp": 1704067200,
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(inputs=create_inputs(include_all_properties=False))

        assert self.get_mock_fetch_calls()[0][1]["body"]["attributes"] == snapshot({"name": "example"})

        self.run_function(inputs=create_inputs(include_all_properties=True))

        assert self.get_mock_fetch_calls()[0][1]["body"]["attributes"] == snapshot(
            {"$current_url": "https://example.com", "name": "example"}
        )

        self.run_function(inputs=create_inputs(include_all_properties=True, action="identify"))

        assert self.get_mock_fetch_calls()[0][1]["body"]["attributes"] == snapshot(
            {"email": "example@posthog.com", "name": "example"}
        )

    def test_automatic_action_mapping(self):
        for event_name, expected_action in [
            ("$identify", "identify"),
            ("$set", "identify"),
            ("$pageview", "page"),
            ("$screen", "screen"),
            ("$autocapture", "event"),
            ("custom", "event"),
        ]:
            self.run_function(
                inputs=create_inputs(),
                globals={
                    "event": {"name": event_name, "properties": {"url": "https://example.com"}},
                },
            )

            assert self.get_mock_fetch_calls()[0][1]["body"]["action"] == expected_action

    def test_enforced_action(self):
        for event_name in [
            "$identify",
            "$pageview",
            "$screen",
            "$autocapture",
            "custom",
        ]:
            self.run_function(
                inputs=create_inputs(action="event"),
                globals={
                    "event": {"name": event_name, "properties": {"url": "https://example.com"}},
                },
            )

            assert self.get_mock_fetch_calls()[0][1]["body"]["action"] == "event"
            assert self.get_mock_fetch_calls()[0][1]["body"]["name"] == event_name

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(identifiers={"email": None, "id": ""}))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot(
            [("No identifier set. Skipping as at least 1 identifier is needed.",)]
        )
