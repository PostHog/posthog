from posthog.test.base import NonAtomicBaseTest
from unittest.mock import ANY, patch

from langchain_core.runnables import RunnableConfig

from ee.hogai.context import AssistantContextManager
from ee.hogai.context.entity_search.context import ENTITY_MAP
from ee.hogai.core.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS
from ee.hogai.tools.full_text_search.tool import EntityKind, EntitySearchTool
from ee.hogai.utils.types.base import AssistantState


class TestEntitySearchToolkit(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()

        self.toolkit = EntitySearchTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=RunnableConfig(configurable={}),
            context_manager=AssistantContextManager(self.team, self.user, {}),
        )

    async def test_arun_no_query(self):
        result = await self.toolkit.execute(query=None, search_kind=EntityKind.COHORTS)  # type: ignore

        assert "No search query was provided" in result

    @patch("ee.hogai.context.entity_search.context.search_entities_fts")
    async def test_search_no_entity_types(self, mock_search_entities):
        all_results: list[dict] = [
            {"type": "cohort", "result_id": "123", "extra_fields": {"name": "Test cohort"}, "rank": 0.95},
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}, "rank": 0.90},
            {"type": "action", "result_id": "101", "extra_fields": {"name": "Test Action"}, "rank": 0.80},
        ]

        def side_effect_func(entities, query, project_id, view, entity_map, limit=100, offset=0):
            return (all_results, dict.fromkeys(entities, 1), len(all_results))

        mock_search_entities.side_effect = side_effect_func

        _ = await self.toolkit.execute(query="test query", search_kind=EntityKind.ALL)

        mock_search_entities.assert_called_once_with(
            set(ENTITY_MAP.keys()), "test query", self.team.project_id, ANY, ENTITY_MAP
        )

    @patch("ee.hogai.context.entity_search.context.search_entities_fts")
    async def test_arun_with_results(self, mock_search_entities):
        all_results: list[dict] = [
            {
                "kind": EntityKind.COHORTS,
                "type": "cohort",
                "result_id": "123",
                "extra_fields": {"name": "Test cohort"},
                "rank": 0.95,
            },
            {
                "kind": EntityKind.DASHBOARDS,
                "type": "dashboard",
                "result_id": "456",
                "extra_fields": {"name": "Test Dashboard"},
                "rank": 0.90,
            },
            {
                "kind": EntityKind.ACTIONS,
                "type": "action",
                "result_id": "101",
                "extra_fields": {"name": "Test Action"},
                "rank": 0.80,
            },
        ]

        def side_effect_func(entities, query, project_id, view, entity_map, limit=100, offset=0):
            result = [result for result in all_results if result["type"] in entities]
            return (result, {result["type"]: len(result) for result in result}, len(result))

        mock_search_entities.side_effect = side_effect_func

        for expected_result in all_results:
            result = await self.toolkit.execute(query="test query", search_kind=expected_result["kind"])
            assert expected_result["type"] in result
            assert expected_result["extra_fields"]["name"] in result
            assert HYPERLINK_USAGE_INSTRUCTIONS in result

    @patch("ee.hogai.context.entity_search.context.database_sync_to_async")
    async def test_arun_exception_handling(self, mock_db_sync):
        async def raise_error(*args, **kwargs):
            raise Exception("Database error")

        mock_db_sync.return_value = raise_error

        with self.assertRaises(Exception) as context:
            await self.toolkit.execute(query="test query", search_kind=EntityKind.DASHBOARDS)

        assert "Database error" in str(context.exception)

    async def test_search_entities_invalid_entity_type(self):
        result = await self.toolkit.execute(query="test query", search_kind="invalid_type")  # type: ignore

        assert "Invalid entity kind: invalid_type. Please provide a valid entity kind for the tool." in result
