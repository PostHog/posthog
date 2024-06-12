from posthog.models.hog_functions.hog_function_template import HogFunctionTemplate
from posthog.test.base import BaseTest
from posthog.models.hog_functions.templates.webhook.template_webhook import template as template_webhook


# TODO: Add base test helper for compiling the function etc.


class BaseHogFunctionTemplateTest(BaseTest):
    template: HogFunctionTemplate

    def setUp(self):
        return super().setUp()


class TestTemplateWebhook(BaseHogFunctionTemplateTest):
    template = template_webhook

    def test_function_compiles(self):
        assert 1 == 2
