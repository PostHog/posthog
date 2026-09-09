from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import OperationalError

from parameterized import parameterized

from ee.hogai.tool_errors import MaxToolTransientError
from ee.hogai.tools.read_taxonomy.core import ReadEventProperties, ReadEvents, ReadTaxonomyToolArgs
from ee.hogai.tools.read_taxonomy.mcp_tool import ReadTaxonomyMCPTool


class TestReadTaxonomyMCPTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ReadTaxonomyMCPTool(team=self.team, user=self.user)

    async def test_tool_has_correct_name(self):
        self.assertEqual(self.tool.name, "read_taxonomy")

    async def test_read_events_returns_yaml(self):
        content = await self.tool.execute(
            ReadTaxonomyToolArgs(query={"kind": "events"}),
        )

        self.assertIn("events:", content)

    async def test_nonexistent_event_returns_empty_properties(self):
        content = await self.tool.execute(
            ReadTaxonomyToolArgs(query={"kind": "event_properties", "event_name": "nonexistent_event"}),
        )

        self.assertIsNotNone(content)

    @parameterized.expand(
        [
            ["statement timeout is retryable", "57014", MaxToolTransientError],
            ["connection loss is not a timeout", "08006", OperationalError],
        ]
    )
    async def test_operational_error_only_treats_statement_timeout_as_transient(
        self, _name: str, sqlstate: str, expected_exception: type[Exception]
    ):
        error = OperationalError("database failure")
        error.sqlstate = sqlstate  # type: ignore[attr-defined]
        with patch(
            "ee.hogai.tools.read_taxonomy.mcp_tool.execute_taxonomy_query",
            side_effect=error,
        ):
            with self.assertRaises(expected_exception):
                await self.tool.execute(
                    ReadTaxonomyToolArgs(query={"kind": "event_properties", "event_name": "$pageview"}),
                )

    async def test_schema_validates_query(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "events"}})
        self.assertEqual(validated.query.kind, "events")

        validated = self.tool.args_schema.model_validate(
            {"query": {"kind": "event_properties", "event_name": "$pageview"}}
        )
        self.assertEqual(validated.query.kind, "event_properties")
        assert isinstance(validated.query, ReadEventProperties)
        self.assertEqual(validated.query.event_name, "$pageview")

    async def test_schema_validates_events_with_pagination(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "events", "limit": 100, "offset": 50}})
        self.assertEqual(validated.query.kind, "events")
        assert isinstance(validated.query, ReadEvents)
        self.assertEqual(validated.query.limit, 100)
        self.assertEqual(validated.query.offset, 50)

    async def test_schema_validates_events_default_pagination(self):
        validated = self.tool.args_schema.model_validate({"query": {"kind": "events"}})
        assert isinstance(validated.query, ReadEvents)
        self.assertEqual(validated.query.limit, 500)
        self.assertEqual(validated.query.offset, 0)
