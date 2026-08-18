import pytest

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.microsoft_teams.template_microsoft_teams import template as template_microsoft_teams


class TestTemplateMicrosoftTeams(BaseHogFunctionTemplateTest):
    template = template_microsoft_teams

    def _inputs(self, **kwargs):
        inputs = {
            "webhookUrl": "https://prod-180.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?api-version=2016-06-01",
            "text": "**max@posthog.com** triggered event: '$pageview'",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(inputs=self._inputs())

        assert self.get_mock_fetch_calls()[0] == (
            "https://prod-180.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?api-version=2016-06-01",
            {
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": {
                    "type": "message",
                    "attachments": [
                        {
                            "contentType": "application/vnd.microsoft.card.adaptive",
                            "contentUrl": None,
                            "content": {
                                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                                "type": "AdaptiveCard",
                                "version": "1.2",
                                "body": [
                                    {
                                        "type": "TextBlock",
                                        "text": "**max@posthog.com** triggered event: '$pageview'",
                                        "wrap": True,
                                    }
                                ],
                            },
                        }
                    ],
                },
            },
        )

    def test_only_allow_teams_url(self):
        format_error = (
            "Invalid URL. The URL should match either Azure Logic Apps format "
            "(https://<region>.logic.azure.com/workflows/...), Power Platform format "
            "(https://<tenant>.webhook.office.com/webhookb2/...), Power Automate format "
            "(https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...), "
            "or Power Platform environment format "
            "(https://<tenant>.environment.api.powerplatform.com/powerautomate/automations/direct/[<cluster>/]workflows/...)"
        )
        host_error = (
            "We recognized the Microsoft Teams host, but not the URL path. Check that you copied "
            "the full webhook URL from Power Automate or Teams, including the path after the host."
        )
        for url, allowed, expected_error in [
            [
                "https://prod-180.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?api-version=2016-06-01",
                True,
                None,
            ],
            # Power Automate hands out Logic Apps URLs without the explicit :443 port
            [
                "https://prod-180.westus.logic.azure.com/workflows/abc/triggers/manual/paths/invoke?api-version=2016-06-01",
                True,
                None,
            ],
            # Trigger name is not always "manual"
            [
                "https://prod-180.westus.logic.azure.com/workflows/abc/triggers/When_a_HTTP_request_is_received/paths/invoke?api-version=2016-06-01",
                True,
                None,
            ],
            [
                "https://tenant.webhook.office.com/webhookb2/guid1/IncomingWebhook/guid2/guid3",
                True,
                None,
            ],
            [
                "https://region.powerautomate.com/workflows/guid1/triggers/manual/guid2",
                True,
                None,
            ],
            [
                "https://region.flow.microsoft.com/workflows/guid1/triggers/manual/guid2",
                True,
                None,
            ],
            [
                "https://tenant.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/guid1/triggers/manual/paths/invoke?api-version=1",
                True,
                None,
            ],
            [
                "https://tenant.environment.api.powerplatform.com/powerautomate/automations/direct/workflows/guid1/triggers/manual/paths/invoke?api-version=1",
                True,
                None,
            ],
            [
                "https://tenant.df.environment.api.powerplatform.com:443/powerautomate/automations/direct/cu/11/workflows/guid1/triggers/manual/paths/invoke?api-version=1",
                True,
                None,
            ],
            # Known host, unusable path: point at the path rather than list every format
            [
                "https://prod-180.westus.logic.azure.com/workflows/abc/triggers/manual/wrong",
                False,
                host_error,
            ],
            ["https://webhook.site/def", False, format_error],
            [
                "https://webhook.site/def#https://prod-180.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?api-version=2016-06-01",
                False,
                format_error,
            ],
        ]:
            if allowed:
                self.run_function(inputs=self._inputs(webhookUrl=url))
                assert len(self.get_mock_fetch_calls()) == 1
                self.mock_fetch.reset_mock()  # Reset mock between tests
            else:
                with pytest.raises(Exception) as e:
                    self.run_function(inputs=self._inputs(webhookUrl=url))
                assert e.value.message == expected_error  # type: ignore[attr-defined]
