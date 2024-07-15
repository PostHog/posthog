from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.intercom.template_intercom import template as template_intercom


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
