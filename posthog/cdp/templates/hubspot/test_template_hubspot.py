from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.hubspot.template_hubspot import template as template_hubspot


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
                "https://api.hubapi.com/crm/v3/objects/contacts",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                    "body": {"properties": {"company": "PostHog", "email": "example@posthog.com"}},
                },
            )
        ]
        assert self.get_mock_print_calls() == [("Contact created successfully!",)]

    def test_exits_if_no_email(self):
        for email in [None, ""]:
            self.mock_print.reset_mock()
            res = self.run_function(inputs=self._inputs(email=email))

            assert res.result is None
            assert self.get_mock_fetch_calls() == []
            assert self.get_mock_print_calls() == [("`email` input is empty. Not creating a contact.",)]

    def test_handles_updates(self):
        call_count = 0

        # First call respond with 409, second one 200 and increment call_count
        def mock_fetch(*args):
            nonlocal call_count
            call_count += 1
            return (
                {"status": 409, "body": {"message": "Contact already exists. Existing ID: 12345"}}
                if call_count == 1
                else {"status": 200, "body": {"status": "success"}}
            )

        self.mock_fetch_response = mock_fetch  # type: ignore

        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert len(self.get_mock_fetch_calls()) == 2

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.hubapi.com/crm/v3/objects/contacts",
            {
                "method": "POST",
                "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                "body": {"properties": {"company": "PostHog", "email": "example@posthog.com"}},
            },
        )

        assert self.get_mock_fetch_calls()[1] == (
            "https://api.hubapi.com/crm/v3/objects/contacts/12345",
            {
                "method": "PATCH",
                "headers": {"Authorization": "Bearer TOKEN", "Content-Type": "application/json"},
                "body": {"properties": {"company": "PostHog", "email": "example@posthog.com"}},
            },
        )
