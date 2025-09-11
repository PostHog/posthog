from inline_snapshot import snapshot

from posthog.cdp.templates.clearbit.template_clearbit import template as template_clearbit
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

EXAMPLE_RESPONSE = {
    "person": {
        "id": "1234",
        "name": {"fullName": "Max the Hedgehog", "givenName": "Max", "familyName": "the Hedgehog"},
        "email": "max@posthog.com",
    },
    "company": {
        "id": "1234",
        "name": "PostHog",
        "legalName": "PostHog Inc.",
        "domain": "posthog.com",
    },
}


class TestTemplateClearbit(BaseHogFunctionTemplateTest):
    template = template_clearbit

    def _inputs(self, **kwargs):
        inputs = {"api_key": "API_KEY", "email": "example@posthog.com"}
        inputs.update(kwargs)
        return inputs

    def test_function_fetches_data(self):
        res = self.run_function(inputs=self._inputs())

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == (
            "https://person-stream.clearbit.com/v2/combined/find?email=example@posthog.com",
            {"method": "GET", "headers": {"Authorization": "Bearer API_KEY"}},
        )

        assert self.get_mock_print_calls() == [("No Clearbit data found",)]

    def test_function_does_not_fetch_data_if_missing_email(self):
        res = self.run_function(inputs=self._inputs(email=""))

        assert res.result is False
        assert self.get_mock_fetch_calls() == []

    def test_function_does_not_fetch_data_if_person_already_enriched(self):
        res = self.run_function(inputs=self._inputs(), globals={"person": {"properties": {"clearbit_enriched": True}}})

        assert res.result is False
        assert self.get_mock_fetch_calls() == []

    def test_function_captures_posthog_event_if_found(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": EXAMPLE_RESPONSE}  # type: ignore

        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[0] == (
            "https://person-stream.clearbit.com/v2/combined/find?email=example@posthog.com",
            {"method": "GET", "headers": {"Authorization": "Bearer API_KEY"}},
        )

        assert self.get_mock_print_calls() == [("Clearbit data found - sending event to PostHog",)]
        assert self.get_mock_posthog_capture_calls() == snapshot(
            [
                (
                    {
                        "event": "$set",
                        "distinct_id": "distinct-id",
                        "properties": {
                            "$lib": "hog_function",
                            "$hog_function_source": "https://us.posthog.com/hog_functions/1234",
                            "$set_once": {
                                "person": {
                                    "id": "1234",
                                    "name": {
                                        "fullName": "Max the Hedgehog",
                                        "givenName": "Max",
                                        "familyName": "the Hedgehog",
                                    },
                                    "email": "max@posthog.com",
                                },
                                "company": {
                                    "id": "1234",
                                    "name": "PostHog",
                                    "legalName": "PostHog Inc.",
                                    "domain": "posthog.com",
                                },
                                "clearbit_enriched": True,
                            },
                        },
                    },
                )
            ]
        )
