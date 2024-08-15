from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.zapier.template_zapier import template as template_zapier


class TestTemplateZapier(BaseHogFunctionTemplateTest):
    template = template_zapier

    def test_function_works(self):
        self.run_function(
            inputs={
                "hook": "hooks/1/2",
                "body": {"hello": "world"},
                "debug": False,
            }
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            ("https://hooks.zapier.com/hooks/1/2", {"body": {"hello": "world"}, "method": "POST"})
        )
        assert self.get_mock_print_calls() == snapshot([])
