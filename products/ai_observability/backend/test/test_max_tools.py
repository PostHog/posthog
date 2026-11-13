from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.facade import (
    api as ai_observability_api,
    contracts,
)
from products.ai_observability.backend.max_tools import CONTEXT_PROMPT_TEMPLATE, DSL_REFERENCE, CreateParserRecipeTool
from products.ai_observability.backend.models.parser_recipe import ParserRecipe

from ee.hogai.utils.types.base import NodePath

VALID_RECIPE = """
rules:
    - on:
          kind: question
      emit:
          role: user
          content: $.body
""".strip()


ARGS = {"name": "My SDK", "yaml_source": VALID_RECIPE, "trace_id": "trace-1", "event_uuid": "event-1"}
FIXED = contracts.TraceParserTestSide(needed_fixing=True, fixed=True, broken=False, error=None)
UNFIXED = contracts.TraceParserTestSide(needed_fixing=True, fixed=False, broken=False, error=None)
FINE = contracts.TraceParserTestSide(needed_fixing=False, fixed=False, broken=False, error=None)
NO_CONTENT = contracts.TraceNodeContent(
    input=contracts.TraceJsonSide(kind="json", value=None), output=contracts.TraceJsonSide(kind="json", value=None)
)


def parser_test(
    input_side: contracts.TraceParserTestSide, output_side: contracts.TraceParserTestSide, *, passed: bool
) -> contracts.TraceNodeParserTest:
    return contracts.TraceNodeParserTest(content=NO_CONTENT, input=input_side, output=output_side, passed=passed)


def error_side(source: str, message: str) -> contracts.TraceParserTestSide:
    return contracts.TraceParserTestSide(
        needed_fixing=True,
        fixed=False,
        broken=False,
        error=contracts.TraceParserTestError(source=source, message=message),
    )


PASSED = parser_test(FIXED, FINE, passed=True)


class TestCreateParserRecipeTool(BaseTest):
    def _create_tool(self) -> CreateParserRecipeTool:
        return CreateParserRecipeTool(
            team=self.team,
            user=self.user,
            node_path=(NodePath(name="root", tool_call_id="call_1", message_id="msg_1"),),
        )

    @parameterized.expand(
        [
            ("not_yaml", "rules: [unclosed", "Recipe YAML does not parse"),
            ("yaml_but_not_a_recipe", "foo: bar", "missing a 'rules:' sequence"),
        ]
    )
    async def test_a_recipe_that_does_not_compile_returns_the_reason(self, _name, yaml_source, expected_error):
        content, artifact = await self._create_tool()._arun_impl(**{**ARGS, "yaml_source": yaml_source})

        self.assertIn(expected_error, content)
        self.assertIsNone(artifact)

    async def test_a_parser_that_passes_is_saved_and_its_id_returned(self):
        with patch.object(ai_observability_api, "run_trace_node_parser_test", return_value=lambda: PASSED):
            content, artifact = await self._create_tool()._arun_impl(**ARGS)

        recipe = await ParserRecipe.objects.unscoped().aget(team=self.team)
        self.assertIn("saved", content)
        self.assertEqual(artifact, {"recipe_id": str(recipe.id), "name": "My SDK", "source": VALID_RECIPE})

    @parameterized.expand(
        [
            ("nothing to fix", parser_test(FINE, FINE, passed=False), "already render"),
            ("a side left unparsed", parser_test(FIXED, UNFIXED, passed=False), "the output is still not parsed"),
            (
                "the recipe failing while it runs",
                parser_test(error_side("candidate", "ran out of time"), FINE, passed=False),
                "ran out of time",
            ),
            (
                "the recipe breaking a side that was parsed",
                parser_test(
                    FIXED,
                    contracts.TraceParserTestSide(needed_fixing=False, fixed=False, broken=True, error=None),
                    passed=False,
                ),
                "the output is parsed without your recipe but not with it",
            ),
            (
                "saved recipes failing on the event",
                parser_test(error_side("existing_recipes", "ran out of time"), FINE, passed=False),
                "not a problem with your recipe",
            ),
        ]
    )
    async def test_a_parser_that_does_not_pass_is_not_saved(self, _name, result, expected):
        with patch.object(ai_observability_api, "run_trace_node_parser_test", return_value=lambda: result):
            content, artifact = await self._create_tool()._arun_impl(**ARGS)

        self.assertIn(expected, content)
        self.assertIsNone(artifact)
        self.assertFalse(await ParserRecipe.objects.unscoped().filter(team=self.team).aexists())

    @parameterized.expand(
        [
            ("an ISO timestamp", "2026-01-02T03:04:05Z", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("one without a zone, read as UTC", "2026-01-02T03:04:05", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("one too close to the end of time for the read window", "9999-12-31T00:00:00+00:00", None),
            ("a garbled value", "(none)", None),
        ]
    )
    async def test_the_trace_timestamp_narrows_the_read_when_usable(self, _name, trace_timestamp, hint):
        with patch.object(ai_observability_api, "run_trace_node_parser_test", return_value=lambda: PASSED) as run:
            await self._create_tool()._arun_impl(**{**ARGS, "trace_timestamp": trace_timestamp})

        self.assertEqual(run.call_args.args[4], hint)

    async def test_an_event_that_cannot_be_read_names_retention(self):
        missing = ai_observability_api.TraceNodeNotFoundError("event-1")
        with patch.object(ai_observability_api, "run_trace_node_parser_test", side_effect=missing):
            content, artifact = await self._create_tool()._arun_impl(**ARGS)

        self.assertIn("past AI events retention", content)
        self.assertIsNone(artifact)

    async def test_a_failed_save_tells_the_agent_not_to_rewrite(self):
        with (
            patch.object(ai_observability_api, "run_trace_node_parser_test", return_value=lambda: PASSED),
            patch.object(ai_observability_api, "create_parser_recipe", side_effect=RuntimeError("500 from API")),
        ):
            content, artifact = await self._create_tool()._arun_impl(**ARGS)

        self.assertIn("Do not rewrite the recipe", content)
        self.assertIn("500 from API", content)
        self.assertEqual(artifact, {"name": "My SDK", "source": VALID_RECIPE})

    def test_context_prompt_template_survives_placeholder_formatting(self):
        tool = self._create_tool()
        context = {
            "trace_id": "trace-1",
            "trace_timestamp": "2026-01-02T03:04:05Z",
            "event_uuid": "0196f8a0-aaaa-bbbb-cccc-000000000000",
            "event_type": "span",
            "unrecognized": "input",
            "sample_input": '{"foo": 1}',
            "sample_output": '{"bar": 2}',
            "existing_recipes": "(none)",
        }

        rendered = tool.format_context_prompt_injection(context)

        assert rendered is not None
        # Any `{identifier}` introduced into the reference would be substituted away and break containment
        self.assertIn('{"foo": 1}', rendered)
        self.assertIn("Event type: span", rendered)
        self.assertIn("Trace ID: trace-1", rendered)
        self.assertIn("Trace timestamp: 2026-01-02T03:04:05Z", rendered)
        self.assertIn(DSL_REFERENCE.strip(), rendered)
        self.assertNotIn("None", rendered)

    def test_context_prompt_template_embeds_dsl_reference(self):
        self.assertIn("examples:", CONTEXT_PROMPT_TEMPLATE)
        self.assertIn("try_parse_structured_content", CONTEXT_PROMPT_TEMPLATE)
