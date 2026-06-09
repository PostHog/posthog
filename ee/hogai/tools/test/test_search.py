from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from langchain_core import messages
from langchain_core.runnables import RunnableConfig

from products.business_knowledge.backend.logic import KnowledgeSearchResult

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolAccessDeniedError, MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.search import (
    BK_READ_NO_RESULTS_TEMPLATE,
    DOC_ITEM_TEMPLATE,
    DOCS_SEARCH_RESULTS_TEMPLATE,
    InkeepDocsSearchTool,
    ReadBusinessKnowledgeTool,
    SearchTool,
    _build_bk_blocks,
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


def _bk_result(document_id, ordinal: int, content: str, source_name: str = "Handbook") -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=uuid4(),
        source_id=uuid4(),
        source_name=source_name,
        source_type="text",
        document_id=document_id,
        document_title="Support handbook",
        heading_path="Refunds",
        ordinal=ordinal,
        content=content,
    )


class TestReadBusinessKnowledgeTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        self.state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = ReadBusinessKnowledgeTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    def _allow_access(self) -> None:
        mock_uac = MagicMock()
        mock_uac.check_access_level_for_resource.return_value = True
        # cached_property: seed the instance cache directly.
        self.tool.__dict__["user_access_control"] = mock_uac

    async def test_unavailable_raises_fatal(self):
        self.tool._has_business_knowledge = False
        with self.assertRaises(MaxToolFatalError):
            await self.tool._arun_impl(document_id=str(uuid4()), around_ordinal=0)

    async def test_access_denied(self):
        self.tool._has_business_knowledge = True
        mock_uac = MagicMock()
        mock_uac.check_access_level_for_resource.return_value = False
        self.tool.__dict__["user_access_control"] = mock_uac
        with self.assertRaises(MaxToolAccessDeniedError):
            await self.tool._arun_impl(document_id=str(uuid4()), around_ordinal=0)

    async def test_invalid_document_id_is_retryable(self):
        self.tool._has_business_knowledge = True
        self._allow_access()
        with self.assertRaises(MaxToolRetryableError):
            await self.tool._arun_impl(document_id="not-a-uuid", around_ordinal=0)

    async def test_returns_formatted_span(self):
        self.tool._has_business_knowledge = True
        self._allow_access()
        doc_id = uuid4()
        results = [
            _bk_result(doc_id, 1, "Chunk one about refunds."),
            _bk_result(doc_id, 2, "Chunk two: thirty day window."),
        ]
        with patch("ee.hogai.tools.search.get_document_window", return_value=results):
            content, artifact = await self.tool._arun_impl(document_id=str(doc_id), around_ordinal=2, radius=1)

        self.assertIsNone(artifact)
        self.assertIn("thirty day window", content)
        self.assertIn("Handbook", content)
        self.assertIn("ordinals 1–2", content)

    async def test_empty_window_returns_no_results_template(self):
        self.tool._has_business_knowledge = True
        self._allow_access()
        with patch("ee.hogai.tools.search.get_document_window", return_value=[]):
            content, artifact = await self.tool._arun_impl(document_id=str(uuid4()), around_ordinal=0)

        self.assertIsNone(artifact)
        self.assertEqual(content, BK_READ_NO_RESULTS_TEMPLATE)

    def test_build_bk_blocks_surfaces_drilldown_handle(self):
        doc_id = uuid4()
        blocks = _build_bk_blocks([_bk_result(doc_id, 3, "Some content")])
        self.assertIn(f"[bk-doc={doc_id} #3]", blocks)
        self.assertIn("Some content", blocks)

    def test_prompts_reference_single_sourced_handle_example(self):
        # Guard against drift: the handle shape quoted in prompt text must come
        # from the same source of truth as the formatter, not be hand-typed.
        from ee.hogai.tools.search import (
            BK_SEARCH_RESULTS_FOOTER,
            BUSINESS_KNOWLEDGE_SEARCH_PROMPT,
            READ_BUSINESS_KNOWLEDGE_PROMPT,
        )
        from ee.hogai.utils.helpers import BK_DRILLDOWN_HANDLE_EXAMPLE

        for prompt in (
            BUSINESS_KNOWLEDGE_SEARCH_PROMPT,
            BK_SEARCH_RESULTS_FOOTER,
            READ_BUSINESS_KNOWLEDGE_PROMPT,
        ):
            self.assertIn(BK_DRILLDOWN_HANDLE_EXAMPLE, prompt)


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
