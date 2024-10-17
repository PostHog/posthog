from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.discord.template_discord import template as template_discord


class TestTemplateDiscord(BaseHogFunctionTemplateTest):
    template = template_discord

    def _inputs(self, **kwargs):
        inputs = {
            "webhookUrl": "https://discord.com/api/webhooks/00000000000000000/xxxxxxxxxxxxxx",
            "content": "**max@posthog.com** triggered event: '$pageview'",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://discord.com/api/webhooks/00000000000000000/xxxxxxxxxxxxxx",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "content": "**max@posthog.com** triggered event: '$pageview'",
                    },
                },
            )
        )
