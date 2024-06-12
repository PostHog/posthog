from typing import Any
from posthog.cdp.templates.hog_function_template import HogFunctionTemplate
from posthog.cdp.templates.webhook.template_webhook import template as template_webhook
from posthog.test.base import BaseTest


# TODO: Add base test helper for compiling the function etc.


class BaseHogFunctionTemplateTest(BaseTest):
    template: HogFunctionTemplate
    compiled_hog: Any

    def setUp(self):
        super().setUp()


        return


class TestTemplateWebhook(BaseHogFunctionTemplateTest):
    template = template_webhook

    def test_function_compiles(self):
        assert 1 == 2
