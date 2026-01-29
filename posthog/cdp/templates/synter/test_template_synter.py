import pytest
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.synter.template_synter import template as template_synter
from common.hogvm.python.utils import UncaughtHogVMException


class TestTemplateSynter(BaseHogFunctionTemplateTest):
    template = template_synter

    def test_function_sends_basic_event(self):
        """Test that basic events are sent correctly to Synter."""
        self.run_function(
            inputs={
                "site_key": "ws_test123",
                "include_person": False,
                "debug": False,
            }
        )

        calls = self.get_mock_fetch_calls()
        assert len(calls) == 1
        
        url, options = calls[0]
        assert url == "https://syntermedia.ai/api/pixel/posthog-webhook"
        assert options["method"] == "POST"
        assert options["headers"]["X-Synter-Site-Key"] == "ws_test123"
        assert options["headers"]["Content-Type"] == "application/json"
        
        body = options["body"]
        assert body["event_name"] == self.event.event
        assert body["event_id"] == str(self.event.uuid)
        assert body["source"] == "posthog"

    def test_function_includes_attribution_click_ids(self):
        """Test that ad platform click IDs are forwarded."""
        self.event.properties = {
            "$current_url": "https://example.com/landing",
            "gclid": "test_gclid_123",
            "fbclid": "test_fbclid_456",
            "ttclid": "test_ttclid_789",
        }
        
        self.run_function(
            inputs={
                "site_key": "ws_test123",
                "include_person": False,
                "debug": False,
            }
        )

        calls = self.get_mock_fetch_calls()
        body = calls[0][1]["body"]
        
        assert body["gclid"] == "test_gclid_123"
        assert body["fbclid"] == "test_fbclid_456"
        assert body["ttclid"] == "test_ttclid_789"
        assert body["page_url"] == "https://example.com/landing"

    def test_function_includes_revenue_data(self):
        """Test that revenue/value data is forwarded."""
        self.event.properties = {
            "value": 99.99,
            "currency": "USD",
        }
        
        self.run_function(
            inputs={
                "site_key": "ws_test123",
                "include_person": False,
                "debug": False,
            }
        )

        calls = self.get_mock_fetch_calls()
        body = calls[0][1]["body"]
        
        assert body["value"] == 99.99
        assert body["currency"] == "USD"

    def test_function_includes_person_when_enabled(self):
        """Test that person properties are included when enabled."""
        self.run_function(
            inputs={
                "site_key": "ws_test123",
                "include_person": True,
                "debug": False,
            }
        )

        calls = self.get_mock_fetch_calls()
        body = calls[0][1]["body"]
        
        assert "person" in body
        assert body["person"]["id"] is not None

    def test_function_excludes_person_when_disabled(self):
        """Test that person properties are excluded when disabled."""
        self.run_function(
            inputs={
                "site_key": "ws_test123",
                "include_person": False,
                "debug": False,
            }
        )

        calls = self.get_mock_fetch_calls()
        body = calls[0][1]["body"]
        
        assert "person" not in body

    def test_function_logs_when_debug_enabled(self):
        """Test that debug logging works."""
        self.run_function(
            inputs={
                "site_key": "ws_test123",
                "include_person": False,
                "debug": True,
            }
        )

        print_calls = self.get_mock_print_calls()
        assert len(print_calls) > 0
        assert "Synter response:" in str(print_calls[0])

    def test_function_no_logs_when_debug_disabled(self):
        """Test that no logging occurs when debug is disabled."""
        self.run_function(
            inputs={
                "site_key": "ws_test123",
                "include_person": False,
                "debug": False,
            }
        )

        print_calls = self.get_mock_print_calls()
        assert len(print_calls) == 0
