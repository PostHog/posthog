from posthog.test.base import NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from ee.hogai.chat_agent.memory.queryable_memory_sync import (
    SIMILARITY_THRESHOLD,
    _has_similar_memory,
    sync_memory_to_queryable,
)


class TestQueryableMemorySync(NonAtomicBaseTest):
    async def test_sync_creates_memory_when_no_similar_exists(self):
        mock_result = MagicMock()
        mock_result.results = []  # No similar memories
        mock_memory = MagicMock()
        mock_memory.contents = "Test memory content"
        mock_memory.team_id = self.team.id
        mock_memory.user_id = self.user.id
        mock_memory.metadata = {"source": "core_memory"}

        with (
            patch(
                "ee.hogai.chat_agent.memory.queryable_memory_sync.execute_hogql_query", return_value=mock_result
            ) as mock_query,
            patch(
                "ee.hogai.chat_agent.memory.queryable_memory_sync._create_queryable_memory",
                return_value=mock_memory,
            ) as mock_create,
        ):
            memory = await sync_memory_to_queryable(self.team, self.user, "Test memory content")

        self.assertIsNotNone(memory)
        self.assertEqual(memory.contents, "Test memory content")
        self.assertEqual(memory.team_id, self.team.id)
        self.assertEqual(memory.user_id, self.user.id)
        self.assertEqual(memory.metadata, {"source": "core_memory"})
        mock_query.assert_called_once()
        mock_create.assert_called_once_with(self.team, self.user, "Test memory content")

    async def test_sync_skips_when_similar_memory_exists(self):
        mock_result = MagicMock()
        mock_result.results = [("existing-id", 0.05)]  # Similar memory found

        with patch(
            "ee.hogai.chat_agent.memory.queryable_memory_sync.execute_hogql_query", return_value=mock_result
        ) as mock_query:
            memory = await sync_memory_to_queryable(self.team, self.user, "Test memory content")

        self.assertIsNone(memory)
        mock_query.assert_called_once()

    async def test_sync_skips_empty_content(self):
        memory = await sync_memory_to_queryable(self.team, self.user, "")
        self.assertIsNone(memory)

        memory = await sync_memory_to_queryable(self.team, self.user, "   ")
        self.assertIsNone(memory)

    async def test_sync_strips_whitespace(self):
        mock_result = MagicMock()
        mock_result.results = []
        mock_memory = MagicMock()
        mock_memory.contents = "Test memory content"

        with (
            patch("ee.hogai.chat_agent.memory.queryable_memory_sync.execute_hogql_query", return_value=mock_result),
            patch(
                "ee.hogai.chat_agent.memory.queryable_memory_sync._create_queryable_memory",
                return_value=mock_memory,
            ),
        ):
            memory = await sync_memory_to_queryable(self.team, self.user, "  Test memory content  ")

        self.assertIsNotNone(memory)
        self.assertEqual(memory.contents, "Test memory content")

    async def test_sync_works_without_user(self):
        mock_result = MagicMock()
        mock_result.results = []
        mock_memory = MagicMock()
        mock_memory.user_id = None

        with (
            patch("ee.hogai.chat_agent.memory.queryable_memory_sync.execute_hogql_query", return_value=mock_result),
            patch(
                "ee.hogai.chat_agent.memory.queryable_memory_sync._create_queryable_memory",
                return_value=mock_memory,
            ),
        ):
            memory = await sync_memory_to_queryable(self.team, None, "Test memory content")

        self.assertIsNotNone(memory)
        self.assertIsNone(memory.user_id)

    async def test_sync_respects_custom_threshold(self):
        mock_result = MagicMock()
        mock_result.results = []
        mock_memory = MagicMock()

        with (
            patch(
                "ee.hogai.chat_agent.memory.queryable_memory_sync.execute_hogql_query", return_value=mock_result
            ) as mock_query,
            patch(
                "ee.hogai.chat_agent.memory.queryable_memory_sync._create_queryable_memory",
                return_value=mock_memory,
            ),
        ):
            await sync_memory_to_queryable(self.team, self.user, "Test", similarity_threshold=0.3)

        # Verify the threshold was passed to the query
        call_args = mock_query.call_args
        placeholders = call_args.kwargs["placeholders"]
        self.assertEqual(placeholders["threshold"].value, 0.3)


class TestHasSimilarMemory(NonAtomicBaseTest):
    async def test_returns_true_when_similar_memory_found(self):
        mock_result = MagicMock()
        mock_result.results = [("existing-id", 0.05)]

        with patch("ee.hogai.chat_agent.memory.queryable_memory_sync.execute_hogql_query", return_value=mock_result):
            result = await _has_similar_memory(self.team, "Test content", SIMILARITY_THRESHOLD)

        self.assertTrue(result)

    async def test_returns_false_when_no_similar_memory(self):
        mock_result = MagicMock()
        mock_result.results = []

        with patch("ee.hogai.chat_agent.memory.queryable_memory_sync.execute_hogql_query", return_value=mock_result):
            result = await _has_similar_memory(self.team, "Test content", SIMILARITY_THRESHOLD)

        self.assertFalse(result)
