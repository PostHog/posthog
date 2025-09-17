from freezegun import freeze_time

from posthog.cdp.templates.braze.template_braze import template as template_braze
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


class TestTemplateBraze(BaseHogFunctionTemplateTest):
    template = template_braze

    @freeze_time("2024-04-16T12:34:51Z")
    def test_function_works(self):
        res = self.run_function(
            inputs={
                "brazeEndpoint": "https://rest.fra-01.braze.eu",
                "apiKey": "my_secret_key",
                "attributes": {"email": "{person.properties.email}"},
                "event": {
                    "name": "{event.event}",
                    "time": "{event.timestamp}",
                    "properties": "{event.properties}",
                    "external_id": "{event.distinct_id}",
                },
            }
        )

        assert res.result is None
        assert self.get_mock_fetch_calls()[0] == (
            "https://rest.fra-01.braze.eu/users/track",
            {
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer my_secret_key",
                },
                "body": [
                    {
                        "attributes": {"email": "{person.properties.email}"},
                        "events": [
                            {
                                "external_id": "{event.distinct_id}",
                                "name": "{event.event}",
                                "properties": "{event.properties}",
                                "time": "{event.timestamp}",
                            },
                        ],
                    }
                ],
                "method": "POST",
            },
        )
