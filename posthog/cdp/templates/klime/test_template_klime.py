import pytest

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.klime.template_klime import template as template_klime

from common.hogvm.python.utils import UncaughtHogVMException


def create_inputs(**kwargs):
    inputs = {
        "writeKey": "test-write-key",
        "action": "automatic",
        "userId": "user-123",
        "groupId": "",
        "include_all_properties": False,
        "properties": {},
    }
    inputs.update(kwargs)
    return inputs


class TestTemplateKlime(BaseHogFunctionTemplateTest):
    template = template_klime

    def test_track_event(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {
                    "uuid": "event-uuid-001",
                    "event": "Button Clicked",
                    "properties": {"$current_url": "https://example.com", "button": "signup"},
                    "timestamp": "2024-01-01T00:00:00Z",
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == (
            "https://i.klime.com/v1/batch",
            {
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer test-write-key",
                },
                "body": {
                    "batch": [
                        {
                            "type": "track",
                            "messageId": "event-uuid-001",
                            "timestamp": "2024-01-01T00:00:00Z",
                            "userId": "user-123",
                            "event": "Button Clicked",
                            "context": {"library": {"name": "posthog-cdp", "version": "1.0.0"}},
                        }
                    ]
                },
            },
        )

    def test_automatic_action_mapping(self):
        for event_name, expected_type in [
            ("$identify", "identify"),
            ("$set", "identify"),
            ("$group_identify", "group"),
            ("custom_event", "track"),
            ("$pageview", "track"),
        ]:
            self.run_function(
                inputs=create_inputs(groupId="group-123"),
                globals={
                    "event": {
                        "uuid": "uuid-1",
                        "event": event_name,
                        "properties": {},
                        "timestamp": "2024-01-01T00:00:00Z",
                    },
                },
            )

            assert self.get_mock_fetch_calls()[0][1]["body"]["batch"][0]["type"] == expected_type

    def test_forced_action_overrides_automatic(self):
        self.run_function(
            inputs=create_inputs(action="track"),
            globals={
                "event": {
                    "uuid": "uuid-1",
                    "event": "$identify",
                    "properties": {},
                    "timestamp": "2024-01-01T00:00:00Z",
                },
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["batch"][0]["type"] == "track"

    def test_include_all_properties_track(self):
        self.run_function(
            inputs=create_inputs(include_all_properties=True),
            globals={
                "event": {
                    "uuid": "uuid-1",
                    "event": "Purchase",
                    "properties": {"$lib": "web", "amount": 99.99, "currency": "USD"},
                    "timestamp": "2024-01-01T00:00:00Z",
                },
            },
        )

        batch_event = self.get_mock_fetch_calls()[0][1]["body"]["batch"][0]
        assert batch_event["properties"] == {"amount": 99.99, "currency": "USD"}

    def test_include_all_properties_identify(self):
        self.run_function(
            inputs=create_inputs(action="identify", include_all_properties=True),
            globals={
                "person": {
                    "id": "person-uuid",
                    "properties": {"email": "test@klime.com", "$creator_event_uuid": "x"},
                },
            },
        )

        batch_event = self.get_mock_fetch_calls()[0][1]["body"]["batch"][0]
        assert batch_event["traits"] == {"email": "test@klime.com"}

    def test_custom_property_mapping(self):
        self.run_function(
            inputs=create_inputs(properties={"plan": "enterprise", "source": "posthog"}),
        )

        batch_event = self.get_mock_fetch_calls()[0][1]["body"]["batch"][0]
        assert batch_event["properties"] == {"plan": "enterprise", "source": "posthog"}

    def test_identify_requires_user_id(self):
        self.run_function(inputs=create_inputs(action="identify", userId=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [
            ("No user ID set. Skipping as user ID is required for identify events.",)
        ]

    def test_group_requires_group_id(self):
        self.run_function(inputs=create_inputs(action="group", groupId=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [("No group ID set. Skipping as group ID is required for group events.",)]

    def test_api_error_raises(self):
        self.mock_fetch_response = lambda *args: {"status": 400, "body": {"error": "invalid request"}}  # type: ignore
        with pytest.raises(UncaughtHogVMException) as e:
            self.run_function(inputs=create_inputs())
        assert "Error from Klime API: 400" in e.value.message
