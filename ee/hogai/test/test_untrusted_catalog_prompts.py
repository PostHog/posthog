from django.test import SimpleTestCase

from parameterized import parameterized

from ee.hogai.chat_agent.sql.prompts import HOGQL_GENERATOR_SYSTEM_PROMPT
from ee.hogai.tools.read_data.prompts import READ_DATA_WAREHOUSE_SCHEMA_PROMPT


class TestUntrustedCatalogPrompts(SimpleTestCase):
    @parameterized.expand(
        [
            ("sql_generator", HOGQL_GENERATOR_SYSTEM_PROMPT),
            ("read_data", READ_DATA_WAREHOUSE_SCHEMA_PROMPT),
        ]
    )
    def test_prompt_marks_relationship_reasoning_as_untrusted(self, _name: str, prompt: str) -> None:
        # `reasoning` on system.information_schema.relationships is project-authored proposal text
        # returned verbatim to the agent; if a prompt edit drops this safeguard, a stored instruction
        # in an accepted proposal can steer a later, higher-privileged Max session. Guard both agents
        # that can query this surface against silently losing the data-not-instructions rule.
        lowered = prompt.lower()
        assert "reasoning" in lowered
        assert "untrusted" in lowered
