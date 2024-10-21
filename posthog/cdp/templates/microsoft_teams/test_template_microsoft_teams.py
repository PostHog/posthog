import pytest
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

    def test_only_allow_teams_url(self):
        for url, allowed in [
            ["https://max.webhook.office.com/webhookb2/abc", True],
            ["https://webhook.site/def", False],
            ["https://webhook.site/def#https://max.webhook.office.com/webhookb2/abc", False],
        ]:
            if allowed:
                self.run_function(inputs=self._inputs(webhookUrl=url))
                assert len(self.get_mock_fetch_calls()) == 1
            else:
                with pytest.raises(Exception) as e:
                    self.run_function(inputs=self._inputs(webhookUrl=url))
                assert (
                    e.value.message
                    == "Invalid URL. The URL should match the format: https://<domain>.webhook.office.com/webhookb2/..."  # type: ignore[attr-defined]
                )
