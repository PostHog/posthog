from langchain_core.prompts import ChatPromptTemplate

from ee.hogai.graph.trends.prompts import REACT_SYSTEM_PROMPT
from posthog.test.base import BaseTest


class TestTrendsPrompts(BaseTest):
    def test_planner_prompt_has_groups(self):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REACT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ).format(
            groups=["org", "account"],
            react_format="",
            react_format_reminder="",
        )
        self.assertIn("orgs, accounts,", prompt)
        self.assertIn("unique orgs", prompt)
        self.assertIn("unique accounts", prompt)
