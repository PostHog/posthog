from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.kudosity.template_kudosity import template as template_kudosity


def create_inputs(**kwargs):
    inputs = {
        "api_key": "test_api_key_123",
        "sender": "Alerts",
        "recipient": "+15555551234",
        "message": "🚨 Alert: {event.properties.insight_name} is {event.properties.current_value} (threshold: {event.properties.threshold_value})",
        "message_ref": "alert_{event.properties.alert_id}",
        "track_links": False,
        "debug": False,
    }
    inputs.update(kwargs)
    return inputs


class TestTemplateKudosity(BaseHogFunctionTemplateTest):
    template = template_kudosity

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {
                    "properties": {
                        "insight_name": "API Error Rate",
                        "current_value": "156",
                        "threshold_value": "100",
                        "alert_id": "alert-123",
                    }
                }
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.transmitmessage.com/v2/sms",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer test_api_key_123",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "message": "🚨 Alert: API Error Rate is 156 (threshold: 100)",
                        "sender": "Alerts",
                        "recipient": "+15555551234",
                        "message_ref": "alert_alert-123",
                        "track_links": False,
                    },
                },
            )
        )

    def test_function_with_track_links_enabled(self):
        self.run_function(
            inputs=create_inputs(track_links=True),
            globals={
                "event": {
                    "properties": {
                        "insight_name": "Conversion Rate",
                        "current_value": "3.2%",
                        "threshold_value": "5%",
                        "alert_id": "alert-456",
                    }
                }
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"] == snapshot(
            {
                "message": "🚨 Alert: Conversion Rate is 3.2% (threshold: 5%)",
                "sender": "Alerts",
                "recipient": "+15555551234",
                "message_ref": "alert_alert-456",
                "track_links": True,
            }
        )

    def test_function_requires_recipient(self):
        self.run_function(inputs=create_inputs(recipient=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No recipient phone number set. Skipping...",)])

    def test_function_requires_message(self):
        self.run_function(inputs=create_inputs(message=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No message set. Skipping...",)])

    def test_function_with_simple_message(self):
        self.run_function(
            inputs=create_inputs(
                message="Simple alert message",
                message_ref="",  # Optional field can be empty
            ),
            globals={"event": {"properties": {}}},
        )

        assert self.get_mock_fetch_calls()[0][1]["body"] == snapshot(
            {
                "message": "Simple alert message",
                "sender": "Alerts",
                "recipient": "+15555551234",
            }
        )

    def test_function_with_debug_mode(self):
        self.run_function(
            inputs=create_inputs(debug=True, message="Test message"),
            globals={"event": {"properties": {}}},
        )

        # Debug mode should print extra information
        print_calls = self.get_mock_print_calls()
        assert len(print_calls) > 0
        assert any("Kudosity SMS Alert" in str(call) for call in print_calls)
