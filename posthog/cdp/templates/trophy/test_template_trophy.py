from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.trophy.template_trophy import template as template_trophy


class TestTemplateTrophy(BaseHogFunctionTemplateTest):
    template = template_trophy

    def _default_inputs(self, **overrides):
        inputs = {
            "api_key": "test_api_key",
            "metric_key": "test_metric",
            "user_id": "user_123",
            "event_value": 1,
            "user_email": "",
            "user_name": "",
            "user_tz": "",
            "user_attributes": {},
            "event_attributes": {},
            "debug": False,
        }
        inputs.update(overrides)
        return inputs

    def test_function_works_minimal(self):
        self.run_function(inputs=self._default_inputs())

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.trophy.so/v1/metrics/test_metric/event",
            {
                "headers": {"Content-Type": "application/json", "X-API-KEY": "test_api_key"},
                "body": {
                    "value": 1,
                    "user": {"id": "user_123"},
                },
                "method": "POST",
            },
        )
        assert self.get_mock_print_calls() == []

    def test_includes_optional_user_fields_when_provided(self):
        self.run_function(
            inputs=self._default_inputs(
                user_email="test@example.com",
                user_name="Test User",
                user_tz="America/New_York",
            )
        )

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.trophy.so/v1/metrics/test_metric/event",
            {
                "headers": {"Content-Type": "application/json", "X-API-KEY": "test_api_key"},
                "body": {
                    "value": 1,
                    "user": {
                        "id": "user_123",
                        "email": "test@example.com",
                        "name": "Test User",
                        "tz": "America/New_York",
                    },
                },
                "method": "POST",
            },
        )

    def test_includes_attributes_when_provided(self):
        self.run_function(
            inputs=self._default_inputs(
                user_attributes={"plan": "pro"},
                event_attributes={"source": "api"},
            )
        )

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.trophy.so/v1/metrics/test_metric/event",
            {
                "headers": {"Content-Type": "application/json", "X-API-KEY": "test_api_key"},
                "body": {
                    "value": 1,
                    "user": {
                        "id": "user_123",
                        "attributes": {"plan": "pro"},
                    },
                    "attributes": {"source": "api"},
                },
                "method": "POST",
            },
        )

    def test_prints_when_debugging(self):
        self.run_function(
            inputs=self._default_inputs(
                debug=True,
                user_email="test@example.com",
            )
        )

        expected_payload = {
            "headers": {"Content-Type": "application/json", "X-API-KEY": "test_api_key"},
            "body": {
                "value": 1,
                "user": {
                    "id": "user_123",
                    "email": "test@example.com",
                },
            },
            "method": "POST",
        }

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.trophy.so/v1/metrics/test_metric/event",
            expected_payload,
        )

        assert self.get_mock_print_calls() == [
            ("Request", "https://api.trophy.so/v1/metrics/test_metric/event", expected_payload),
            ("Response", 200, {}),
        ]
