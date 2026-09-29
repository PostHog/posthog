import asyncio
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings

from langchain_core import messages
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.docs_search_shadow import compare_docs_results, fetch_inkeep_with_shadow, inkeep_result_urls
from ee.hogai.tools.search import (
    DOC_ITEM_TEMPLATE,
    DOCS_SEARCH_NO_RESULTS_TEMPLATE,
    DOCS_SEARCH_RESULTS_TEMPLATE,
    InkeepDocsSearchTool,
    SearchTool,
    format_inkeep_docs_response,
)
from ee.hogai.utils.tests import FakeChatOpenAI
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class TestSearchTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        self.state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = SearchTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    async def test_run_docs_search_without_api_key(self):
        with patch("ee.hogai.tools.search.settings") as mock_settings:
            mock_settings.INKEEP_API_KEY = None
            with self.assertRaises(MaxToolFatalError) as context:
                await self.tool._arun_impl(kind="docs", query="How to use feature flags?")

            error_message = str(context.exception)
            self.assertIn("not available", error_message.lower())

    async def test_run_docs_search_with_api_key(self):
        mock_docs_tool = MagicMock()
        mock_docs_tool.execute = AsyncMock(return_value=("", MagicMock()))

        with (
            patch("ee.hogai.tools.search.settings") as mock_settings,
            patch("ee.hogai.tools.search.InkeepDocsSearchTool", return_value=mock_docs_tool),
        ):
            mock_settings.INKEEP_API_KEY = "test-key"
            result, artifact = await self.tool._arun_impl(kind="docs", query="How to use feature flags?")

            mock_docs_tool.execute.assert_called_once_with("How to use feature flags?", self.tool_call_id)
            self.assertEqual(result, "")
            self.assertIsNotNone(artifact)

    async def test_run_unknown_kind(self):
        with self.assertRaises(MaxToolRetryableError) as context:
            await self.tool._arun_impl(kind="unknown", query="test")

        error_message = str(context.exception)
        self.assertIn("Invalid entity kind", error_message)
        self.assertIn("unknown", error_message)


class TestInkeepDocsSearchTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = str(uuid4())
        self.state = AssistantState(messages=[], root_tool_call_id=self.tool_call_id)
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = InkeepDocsSearchTool(
            team=self.team,
            user=self.user,
            state=self.state,
            config=RunnableConfig(configurable={}),
            context_manager=self.context_manager,
        )

    @override_settings(INKEEP_API_KEY="test-inkeep-key")
    @patch("ee.hogai.tools.search.ChatOpenAI")
    async def test_search_docs_with_successful_results(self, mock_llm_class):
        response_json = """{
            "content": [
                {
                    "type": "document",
                    "record_type": "page",
                    "url": "https://posthog.com/docs/feature",
                    "title": "Feature Documentation",
                    "source": {
                        "type": "text",
                        "content": [{"type": "text", "text": "This is documentation about the feature."}]
                    }
                },
                {
                    "type": "document",
                    "record_type": "guide",
                    "url": "https://posthog.com/docs/guide",
                    "title": "Setup Guide",
                    "source": {"type": "text", "content": [{"type": "text", "text": "How to set up the feature."}]}
                }
            ]
        }"""

        fake_llm = FakeChatOpenAI(responses=[messages.AIMessage(content=response_json)])
        mock_llm_class.return_value = fake_llm

        result, _ = await self.tool.execute("how to use feature", "test-tool-call-id")

        expected_doc_1 = DOC_ITEM_TEMPLATE.format(
            title="Feature Documentation",
            url="https://posthog.com/docs/feature",
            text="This is documentation about the feature.",
        )
        expected_doc_2 = DOC_ITEM_TEMPLATE.format(
            title="Setup Guide", url="https://posthog.com/docs/guide", text="How to set up the feature."
        )
        expected_result = DOCS_SEARCH_RESULTS_TEMPLATE.format(
            count=2, docs=f"{expected_doc_1}\n\n---\n\n{expected_doc_2}"
        )

        self.assertEqual(result, expected_result)
        mock_llm_class.assert_called_once()
        self.assertEqual(mock_llm_class.call_args.kwargs["model"], "inkeep-rag")
        self.assertEqual(mock_llm_class.call_args.kwargs["base_url"], "https://api.inkeep.com/v1/")
        self.assertEqual(mock_llm_class.call_args.kwargs["api_key"], "test-inkeep-key")
        self.assertEqual(mock_llm_class.call_args.kwargs["streaming"], False)


class TestFormatInkeepDocsResponse(SimpleTestCase):
    @staticmethod
    def _payload(*urls: str) -> dict:
        return {
            "content": [
                {
                    "type": "document",
                    "record_type": "page",
                    "url": url,
                    "title": f"Title for {url}",
                    "source": {"type": "text", "content": [{"type": "text", "text": "Body"}]},
                }
                for url in urls
            ]
        }

    @parameterized.expand(
        [
            ("community_question", "https://posthog.com/questions/how-do-i-mask-inputs", False),
            ("community_question_www", "https://www.posthog.com/questions/how-do-i-mask-inputs", False),
            ("community_questions_index", "https://posthog.com/questions", False),
            ("docs_page", "https://posthog.com/docs/session-replay/privacy", True),
            ("docs_common_questions", "https://posthog.com/docs/data/common-questions", True),
            ("tutorial", "https://posthog.com/tutorials/session-recordings-for-support", True),
            ("github_issue", "https://github.com/PostHog/posthog-js/issues/2292", True),
        ]
    )
    def test_filters_community_questions(self, _name: str, url: str, expected_included: bool) -> None:
        result = format_inkeep_docs_response(self._payload(url, "https://posthog.com/docs/getting-started"))

        self.assertEqual(url in result, expected_included)

    def test_returns_no_results_when_every_result_is_a_community_question(self) -> None:
        result = format_inkeep_docs_response(self._payload("https://posthog.com/questions/why-no-recordings"))

        self.assertEqual(result, DOCS_SEARCH_NO_RESULTS_TEMPLATE)


def _docs_payload(*docs: tuple[str, str]) -> dict:
    return {
        "content": [
            {
                "type": doc_type,
                "record_type": "page",
                "url": url,
                "title": url,
                "source": {"type": "text", "content": [{"type": "text", "text": "Body"}]},
            }
            for doc_type, url in docs
        ]
    }


class TestDocsShadowOverlap(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "normalizes_host_query_and_slash",
                _docs_payload(("document", "https://www.PostHog.com/docs/flags/?q=1#section")),
                ["https://posthog.com/docs/flags/"],
                1,
                True,
                1,
                1.0,
            ),
            (
                "drops_community_questions",
                _docs_payload(
                    ("document", "https://posthog.com/questions/how-do-i-mask-inputs"),
                    ("document", "https://posthog.com/docs/session-replay"),
                    ("other", "https://posthog.com/docs/ignored"),
                ),
                [
                    "https://posthog.com/questions/how-do-i-mask-inputs",
                    "https://posthog.com/docs/session-replay",
                ],
                1,
                False,
                2,
                1.0,
            ),
            (
                "empty_business_knowledge",
                _docs_payload(("document", "https://posthog.com/docs/flags")),
                [],
                0,
                False,
                0,
                0.0,
            ),
            (
                "duplicate_chunks_count_once",
                _docs_payload(("document", "https://posthog.com/docs/flags")),
                ["https://posthog.com/docs/flags", "https://posthog.com/docs/flags#install"],
                1,
                True,
                1,
                1.0,
            ),
            (
                "skips_url_with_invalid_port",
                _docs_payload(
                    ("document", "https://posthog.com:99999/docs/other"),
                    ("document", "https://posthog.com/docs/flags"),
                ),
                ["https://posthog.com/docs/flags"],
                1,
                True,
                1,
                1.0,
            ),
        ]
    )
    def test_overlap(
        self,
        _name: str,
        payload: dict,
        bk_urls: list[str],
        overlap_count: int,
        top1_match: bool,
        bk_count: int,
        recall_at_k: float,
    ) -> None:
        comparison = compare_docs_results(inkeep_result_urls(payload), bk_urls)
        self.assertEqual(comparison.overlap_count, overlap_count)
        self.assertEqual(comparison.top1_match, top1_match)
        self.assertEqual(comparison.bk_count, bk_count)
        self.assertEqual(comparison.inkeep_count, 1)
        self.assertEqual(comparison.recall_at_k, recall_at_k)


class TestDocsShadowFailure(SimpleTestCase):
    @parameterized.expand(
        [
            ("timeout", True),
            ("exception", False),
        ]
    )
    async def test_bk_failure_leaves_inkeep_output_unchanged(self, _name: str, hang: bool) -> None:
        payload = _docs_payload(("document", "https://posthog.com/docs/flags"))
        expected = format_inkeep_docs_response(payload, include_system_reminder=False)

        async def fetch_inkeep() -> dict:
            return payload

        async def bk_search(*_args: object, **_kwargs: object) -> list:
            if hang:
                await asyncio.Event().wait()
            raise RuntimeError("search down")

        team = MagicMock()
        team.id = 1
        team.organization_id = "org"
        team.uuid = "team-uuid"

        with (
            patch("ee.hogai.tools.docs_search_shadow.has_docs_shadow_feature_flag", return_value=True),
            patch("ee.hogai.tools.docs_search_shadow.async_search_knowledge_for_team", bk_search),
            patch("ee.hogai.tools.docs_search_shadow.SHADOW_TIMEOUT_SECONDS", 0.05),
            patch("ee.hogai.tools.docs_search_shadow.posthoganalytics.capture") as capture,
        ):
            result = await fetch_inkeep_with_shadow(
                team=team,
                query="how do flags work",
                fetch_inkeep=fetch_inkeep,
                surface="posthog_ai",
            )

        self.assertEqual(result, payload)
        self.assertEqual(format_inkeep_docs_response(result, include_system_reminder=False), expected)
        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs["properties"]["bk_error"], "timeout" if hang else "exception")
        self.assertEqual(capture.call_args.kwargs["distinct_id"], "team-uuid")
        self.assertNotIn("how do flags work", str(capture.call_args.kwargs["properties"]))

    async def test_flag_off_does_not_search_or_capture(self) -> None:
        payload = _docs_payload(("document", "https://posthog.com/docs/flags"))
        called = False

        async def fetch_inkeep() -> dict:
            return payload

        async def bk_search(*_args: object, **_kwargs: object) -> list:
            nonlocal called
            called = True
            return []

        team = MagicMock()
        team.id = 1
        team.organization_id = "org"
        team.uuid = "team-uuid"

        with (
            patch("ee.hogai.tools.docs_search_shadow.has_docs_shadow_feature_flag", return_value=False),
            patch("ee.hogai.tools.docs_search_shadow.async_search_knowledge_for_team", bk_search),
            patch("ee.hogai.tools.docs_search_shadow.posthoganalytics.capture") as capture,
        ):
            result = await fetch_inkeep_with_shadow(
                team=team,
                query="how do flags work",
                fetch_inkeep=fetch_inkeep,
                surface="mcp",
            )

        self.assertEqual(result, payload)
        self.assertFalse(called)
        capture.assert_not_called()

    @parameterized.expand(
        [
            ("flag",),
            ("capture",),
        ]
    )
    async def test_bookkeeping_failure_leaves_inkeep_output_unchanged(self, kind: str) -> None:
        payload = _docs_payload(("document", "https://posthog.com/docs/flags"))
        expected = format_inkeep_docs_response(payload, include_system_reminder=False)
        searched = False

        async def fetch_inkeep() -> dict:
            return payload

        async def bk_search(*_args: object, **_kwargs: object) -> list:
            nonlocal searched
            searched = True
            return []

        team = MagicMock()
        team.id = 1
        team.organization_id = "org"
        team.uuid = "team-uuid"

        flag_effect = RuntimeError("flag down") if kind == "flag" else None
        with (
            patch(
                "ee.hogai.tools.docs_search_shadow.has_docs_shadow_feature_flag",
                return_value=True,
                side_effect=flag_effect,
            ),
            patch("ee.hogai.tools.docs_search_shadow.async_search_knowledge_for_team", bk_search),
            patch(
                "ee.hogai.tools.docs_search_shadow.posthoganalytics.capture",
                side_effect=RuntimeError("capture down"),
            ),
        ):
            result = await fetch_inkeep_with_shadow(
                team=team,
                query="how do flags work",
                fetch_inkeep=fetch_inkeep,
                surface="mcp",
            )

        self.assertEqual(result, payload)
        self.assertEqual(format_inkeep_docs_response(result, include_system_reminder=False), expected)
        self.assertEqual(searched, kind == "capture")

    async def test_search_that_swallows_cancellation_does_not_hold_the_response(self) -> None:
        payload = _docs_payload(("document", "https://posthog.com/docs/flags"))
        release = asyncio.Event()

        async def fetch_inkeep() -> dict:
            return payload

        async def bk_search(*_args: object, **_kwargs: object) -> list:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                raise
            return []

        team = MagicMock()
        team.id = 1
        team.organization_id = "org"
        team.uuid = "team-uuid"

        try:
            with (
                patch("ee.hogai.tools.docs_search_shadow.has_docs_shadow_feature_flag", return_value=True),
                patch("ee.hogai.tools.docs_search_shadow.async_search_knowledge_for_team", bk_search),
                patch("ee.hogai.tools.docs_search_shadow.SHADOW_TIMEOUT_SECONDS", 0.05),
                patch("ee.hogai.tools.docs_search_shadow.posthoganalytics.capture") as capture,
            ):
                result = await asyncio.wait_for(
                    fetch_inkeep_with_shadow(
                        team=team,
                        query="how do flags work",
                        fetch_inkeep=fetch_inkeep,
                        surface="posthog_ai",
                    ),
                    timeout=1,
                )
        finally:
            release.set()

        self.assertEqual(result, payload)
        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs["properties"]["bk_error"], "timeout")
