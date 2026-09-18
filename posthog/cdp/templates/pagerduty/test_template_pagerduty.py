import pytest

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.pagerduty.template_pagerduty import template as template_pagerduty

US_ENDPOINT = "https://events.pagerduty.com/v2/enqueue"
EU_ENDPOINT = "https://events.eu.pagerduty.com/v2/enqueue"


class TestTemplatePagerDuty(BaseHogFunctionTemplateTest):
    template = template_pagerduty

    def _inputs(self, **kwargs):
        inputs = {
            "routing_key": "0123456789abcdef0123456789abcdef",
            "region": "us",
            "event_action": "trigger",
            "dedup_key": "posthog-alert-alert-1",
            "summary": "Log alert 'Errors' is firing: 120 logs in 5m",
            "source": "My project",
            "severity": "critical",
            "custom_details": {"Threshold breached": "120 logs in 5m"},
            "links": [{"href": "https://example.com/logs", "text": "View logs"}],
            "client_url": "https://example.com/logs",
        }
        inputs.update(kwargs)
        return inputs

    def test_sends_a_complete_events_api_v2_event(self):
        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[0] == (
            US_ENDPOINT,
            {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "routing_key": "0123456789abcdef0123456789abcdef",
                    "event_action": "trigger",
                    "dedup_key": "posthog-alert-alert-1",
                    "payload": {
                        "summary": "Log alert 'Errors' is firing: 120 logs in 5m",
                        "source": "My project",
                        "severity": "critical",
                        "custom_details": {"Threshold breached": "120 logs in 5m"},
                    },
                    "client": "PostHog",
                    "client_url": "https://example.com/logs",
                    "links": [{"href": "https://example.com/logs", "text": "View logs"}],
                },
            },
        )

    @parameterized.expand([["us", US_ENDPOINT], ["eu", EU_ENDPOINT]])
    def test_region_selects_the_endpoint(self, region, expected_endpoint):
        self.run_function(inputs=self._inputs(region=region))

        assert self.get_mock_fetch_calls()[0][0] == expected_endpoint

    def test_empty_optional_inputs_are_left_out_of_the_event(self):
        self.run_function(inputs=self._inputs(dedup_key="", custom_details={}, links=[], client_url=""))

        body = self.get_mock_fetch_calls()[0][1]["body"]
        assert "dedup_key" not in body
        assert "links" not in body
        assert "client_url" not in body
        assert "custom_details" not in body["payload"]

    def test_a_rejected_event_raises(self):
        self.fetch_responses = {US_ENDPOINT: {"status": 400, "body": {"status": "invalid event"}}}

        with pytest.raises(Exception) as e:
            self.run_function(inputs=self._inputs())

        assert "Failed to send event to PagerDuty: 400" in e.value.message  # type: ignore[attr-defined]
