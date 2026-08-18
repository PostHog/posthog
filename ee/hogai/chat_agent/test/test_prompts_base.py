from django.test import SimpleTestCase

from ee.hogai.chat_agent.prompts.base import TOOL_USAGE_POLICY_PROMPT, get_tool_usage_policy_prompt


class TestToolUsagePolicyPrompt(SimpleTestCase):
    def test_web_search_line_present_when_available(self):
        prompt = get_tool_usage_policy_prompt(web_search_available=True)
        self.assertIn("web_search", prompt)
        # Existing importers rely on the default constant staying identical to the available form.
        self.assertEqual(prompt, TOOL_USAGE_POLICY_PROMPT)

    def test_web_search_line_dropped_when_unavailable(self):
        prompt = get_tool_usage_policy_prompt(web_search_available=False)
        self.assertNotIn("web_search", prompt)
        # The rest of the policy is untouched.
        self.assertIn("<tool_usage_policy>", prompt)
        self.assertIn("Retry failed tool calls", prompt)
