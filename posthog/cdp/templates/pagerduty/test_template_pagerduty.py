import pytest

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.pagerduty.template_pagerduty import template as template_pagerduty

ENQUEUE_URL = "https://events.pagerduty.com/v2/enqueue"


class TestTemplatePagerDuty(BaseHogFunctionTemplateTest):
    template = template_pagerduty

    def _inputs(self, **kwargs):
        inputs = {
            "routing_key": "abcdef0123456789abcdef0123456789",
            "event_action": "trigger",
            "dedup_key": "posthog-alert-1",
            "summary": "Log alert 'Checkout errors' is firing",
            "source": "My project",
            "severity": "critical",
            "component": "logs alert",
            "event_class": "firing",
            "custom_details": {"threshold": 100},
            "links": [{"href": "https://example.com/alert", "text": "View alert"}],
        }
        inputs.update(kwargs)
        return inputs

    def test_trigger_sends_an_events_api_v2_body(self):
        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[0] == (
            ENQUEUE_URL,
            {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "routing_key": "abcdef0123456789abcdef0123456789",
                    "event_action": "trigger",
                    "dedup_key": "posthog-alert-1",
                    "payload": {
                        "summary": "Log alert 'Checkout errors' is firing",
                        "source": "My project",
                        "severity": "critical",
                        "component": "logs alert",
                        "class": "firing",
                        "custom_details": {"threshold": 100},
                    },
                    "client": "PostHog",
                    "links": [{"href": "https://example.com/alert", "text": "View alert"}],
                },
            },
        )

    def test_trigger_leaves_out_empty_optional_fields(self):
        self.run_function(
            inputs=self._inputs(dedup_key="", component="", event_class="", custom_details={}, links=[]),
        )

        body = self.get_mock_fetch_calls()[0][1]["body"]
        assert "dedup_key" not in body
        assert "links" not in body
        assert body["payload"] == {
            "summary": "Log alert 'Checkout errors' is firing",
            "source": "My project",
            "severity": "critical",
        }

    @parameterized.expand([["resolve"], ["acknowledge"]])
    def test_resolve_and_acknowledge_send_only_the_key_fields(self, action):
        self.run_function(inputs=self._inputs(event_action=action))

        assert self.get_mock_fetch_calls()[0][1]["body"] == {
            "routing_key": "abcdef0123456789abcdef0123456789",
            "event_action": action,
            "dedup_key": "posthog-alert-1",
        }

    @parameterized.expand([["resolve"], ["acknowledge"]])
    def test_resolve_and_acknowledge_require_a_dedup_key(self, action):
        with pytest.raises(Exception) as e:
            self.run_function(inputs=self._inputs(event_action=action, dedup_key=""))

        assert e.value.message == f"A dedup key is required to {action} an incident."  # type: ignore[attr-defined]
        assert self.get_mock_fetch_calls() == []

    @parameterized.expand([["high"], [""], [None]])
    def test_an_unknown_severity_is_sent_as_error(self, severity):
        self.run_function(inputs=self._inputs(severity=severity))

        assert self.get_mock_fetch_calls()[0][1]["body"]["payload"]["severity"] == "error"

    def test_summary_is_cut_to_the_pagerduty_limit(self):
        self.run_function(inputs=self._inputs(summary="x" * 2000))

        assert len(self.get_mock_fetch_calls()[0][1]["body"]["payload"]["summary"]) == 1024

    def test_an_unknown_event_action_throws(self):
        with pytest.raises(Exception) as e:
            self.run_function(inputs=self._inputs(event_action="page"))

        assert (
            e.value.message  # type: ignore[attr-defined]
            == 'Unsupported event action "page". Use trigger, acknowledge or resolve.'
        )

    def test_a_rejected_event_throws(self):
        self.fetch_responses = {ENQUEUE_URL: {"status": 400, "body": {"message": "Invalid routing key"}}}
        with pytest.raises(Exception) as e:
            self.run_function(inputs=self._inputs())

        assert "PagerDuty rejected the event: 400" in e.value.message  # type: ignore[attr-defined]
