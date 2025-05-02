from langchain_core.messages import AIMessage as LangchainAIMessage

from ee.hogai.graph.taxonomy_agent.parsers import (
    ReActParserMalformedJsonException,
    ReActParserMissingActionException,
    parse_react_agent_output,
)
from posthog.test.base import BaseTest


class TestTaxonomyAgentParsers(BaseTest):
    def test_parse_react_agent_output(self):
        res = parse_react_agent_output(
            LangchainAIMessage(
                content="""
                        Some thoughts...
                        Action:
                        ```json
                        {"action": "action_name", "action_input": "action_input"}
                        ```
                        """
            )
        )
        self.assertEqual(res.tool, "action_name")
        self.assertEqual(res.tool_input, "action_input")

        res = parse_react_agent_output(
            LangchainAIMessage(
                content="""
                        Some thoughts...
                        Action:
                        ```
                        {"action": "tool", "action_input": {"key": "value"}}
                        ```
                        """
            )
        )
        self.assertEqual(res.tool, "tool")
        self.assertEqual(res.tool_input, {"key": "value"})

        self.assertRaises(
            ReActParserMissingActionException, parse_react_agent_output, LangchainAIMessage(content="Some thoughts...")
        )
        self.assertRaises(
            ReActParserMalformedJsonException,
            parse_react_agent_output,
            LangchainAIMessage(content="Some thoughts...\nAction: abc"),
        )
        self.assertRaises(
            ReActParserMalformedJsonException,
            parse_react_agent_output,
            LangchainAIMessage(content="Some thoughts...\nAction:"),
        )
        self.assertRaises(
            ReActParserMalformedJsonException,
            parse_react_agent_output,
            LangchainAIMessage(content="Some thoughts...\nAction: {}"),
        )
        self.assertRaises(
            ReActParserMalformedJsonException,
            parse_react_agent_output,
            LangchainAIMessage(content="Some thoughts...\nAction:\n```\n{}\n```"),
        )
        self.assertRaises(
            ReActParserMalformedJsonException,
            parse_react_agent_output,
            LangchainAIMessage(content="Some thoughts...\nAction:\n```\n{not a json}\n```"),
        )
        self.assertRaises(
            ReActParserMalformedJsonException,
            parse_react_agent_output,
            LangchainAIMessage(content='Some thoughts...\nAction:\n```\n{"action":"tool"}\n```'),
        )
        self.assertRaises(
            ReActParserMalformedJsonException,
            parse_react_agent_output,
            LangchainAIMessage(content='Some thoughts...\nAction:\n```\n{"action_input":"input"}\n```'),
        )
