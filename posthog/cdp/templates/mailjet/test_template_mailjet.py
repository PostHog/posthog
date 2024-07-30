from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.mailjet.template_mailjet import template_create_contact


class TestTemplateMailjetCreateContact(BaseHogFunctionTemplateTest):
    template = template_create_contact

    def _inputs(self, **kwargs):
        inputs = {"api_key": "API_KEY", "email": "example@posthog.com"}
        inputs.update(kwargs)
        return inputs

    def test_function_fetches_data(self):
        res = self.run_function(inputs=self._inputs())
        assert False == True
