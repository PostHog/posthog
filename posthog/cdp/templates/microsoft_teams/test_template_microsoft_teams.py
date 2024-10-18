from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.microsoft_teams.template_microsoft_teams import template as template_microsoft_teams


class TestTemplateMicrosoftTeams(BaseHogFunctionTemplateTest):
    template = template_microsoft_teams

    def _inputs(self, **kwargs):
        inputs = {
            "webhookUrl": "https://max.webhook.office.com/webhookb2/abcdefg@abcdefg/IncomingWebhook/abcdefg/abcdefg",
            "content": "**max@posthog.com** triggered event: '$pageview'",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://max.webhook.office.com/webhookb2/abcdefg@abcdefg/IncomingWebhook/abcdefg/abcdefg",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "text": "**max@posthog.com** triggered event: '$pageview'",
                    },
                },
            )
        )
