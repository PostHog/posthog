from django.test import SimpleTestCase

from ee.hogai.chat_agent.prompts.base import BASIC_FUNCTIONALITY_PROMPT


class TestChatAgentPrompts(SimpleTestCase):
    def test_basic_functionality_prompt_teaches_sql_variable_discovery(self):
        self.assertIn("SQL variables", BASIC_FUNCTIONALITY_PROMPT)
        self.assertIn("system.insight_variables", BASIC_FUNCTIONALITY_PROMPT)
