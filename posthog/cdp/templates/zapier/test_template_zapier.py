from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.zapier.template_zapier import template as template_zapier


class TestTemplateZapier(BaseHogFunctionTemplateTest):
    template = template_zapier

    def test_function_works_with_path_only(self):
        # Test with just the path
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

    def test_function_strips_url_prefix(self):
        # Test with a full URL including the prefix
        self.run_function(
            inputs={
                "hook": "https://hooks.zapier.com/hooks/catch/7363152/2l3ak6v/",
                "body": {"hello": "world"},
                "debug": False,
            }
        )

        # The URL prefix should be stripped, so the fetch call should use just the path
        assert self.get_mock_fetch_calls()[0] == snapshot(
            ("https://hooks.zapier.com/hooks/catch/7363152/2l3ak6v/", {"body": {"hello": "world"}, "method": "POST"})
        )
        assert self.get_mock_print_calls() == snapshot([])
