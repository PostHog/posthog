import pytest

from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.make.template_make import template as template_make


class TestTemplateMake(BaseHogFunctionTemplateTest):
    template = template_make

    def _inputs(self, **kwargs):
        inputs = {
            "webhookUrl": "https://hook.xxx.make.com/xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "body": {
                "data": {
                    "eventUuid": "uuid-xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "event": "$pageview",
                    "teamId": "teamId-xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "distinctId": "distinctId-xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "properties": {"uuid": "person-uuid-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
                }
            },
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://hook.xxx.make.com/xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "data": {
                            "eventUuid": "uuid-xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                            "event": "$pageview",
                            "teamId": "teamId-xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                            "distinctId": "distinctId-xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                            "properties": {"uuid": "person-uuid-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
                        }
                    },
                },
            )
        )

    def test_only_allow_teams_url(self):
        for url, allowed in [
            ["https://hook.xxx.make.com/xxxxxxxxxxxxxxxxxxxxxxxxxxxx", True],
            ["https://webhook.site/def", False],
            ["https://webhook.site/def#https://hook.xxx.make.com/xxxxxxxxxxxxxxxxxxxxxxxxxxxx", False],
        ]:
            if allowed:
                self.run_function(inputs=self._inputs(webhookUrl=url))
                assert len(self.get_mock_fetch_calls()) == 1
            else:
                with pytest.raises(Exception) as e:
                    self.run_function(inputs=self._inputs(webhookUrl=url))
                assert (
                    e.value.message  # type: ignore[attr-defined]
                    == "Invalid URL. The URL should match the format: https://hook.<region>.make.com/<hookUrl>"
                )
