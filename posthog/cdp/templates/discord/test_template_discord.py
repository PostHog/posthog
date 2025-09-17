import pytest

from inline_snapshot import snapshot

from posthog.cdp.templates.discord.template_discord import template as template_discord
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


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

    def test_only_allow_teams_url(self):
        for url, allowed in [
            ["https://discord.com/api/webhooks/abc", True],
            ["https://webhook.site/def", False],
            ["https://webhook.site/def#https://discord.com/api/webhooks/abc", False],
        ]:
            if allowed:
                self.run_function(inputs=self._inputs(webhookUrl=url))
                assert len(self.get_mock_fetch_calls()) == 1
            else:
                with pytest.raises(Exception) as e:
                    self.run_function(inputs=self._inputs(webhookUrl=url))
                assert (
                    e.value.message  # type: ignore[attr-defined]
                    == "Invalid URL. The URL should match the format: https://discord.com/api/webhooks/..."
                )
