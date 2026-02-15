from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig

from ee.hogai.context import AssistantContextManager
from ee.hogai.tools.create_notebook.tool import CreateNotebookTool
from ee.hogai.utils.types.base import AssistantState, NodePath
from ee.models.assistant import Conversation


class TestCreateNotebookTool(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        self.context_manager = AssistantContextManager(self.team, self.user, self.config)
        self.tool_call_id = "test_tool_call_id"
        self.node_path = (NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),)
        self.tool = CreateNotebookTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=self.config,
            context_manager=self.context_manager,
            node_path=self.node_path,
        )

    def test_returns_error_when_both_content_and_draft_content_provided(self):
        result, artifact = async_to_sync(self.tool._arun_impl)(
            title="Test Notebook",
            content="# Hello",
            draft_content="# Draft Hello",
        )

        assert "Cannot provide both" in result
        assert "Use exactly one" in result
        assert artifact is None

    def test_returns_error_when_neither_content_nor_draft_content_provided(self):
        result, artifact = async_to_sync(self.tool._arun_impl)(
            title="Test Notebook",
            content=None,
            draft_content=None,
        )

        assert "Either 'content' or 'draft_content' must be provided" in result
        assert artifact is None

    def test_creates_notebook_with_content(self):
        result, artifact = async_to_sync(self.tool._arun_impl)(
            title="Test Notebook",
            content="# Hello World",
        )

        assert result == ""
        assert artifact is not None
        assert len(artifact.messages) == 2

    def test_creates_draft_notebook_without_streaming(self):
        result, artifact = async_to_sync(self.tool._arun_impl)(
            title="Test Draft",
            draft_content="# Draft Content",
        )

        assert "artifact_id" in result
        assert artifact is None

    def test_update_failure_falls_back_to_create(self):
        result, artifact = async_to_sync(self.tool._arun_impl)(
            title="Test Notebook",
            content="# Hello",
            artifact_id="nonexistent_artifact_id",
        )

        assert result == ""
        assert artifact is not None
        assert len(artifact.messages) == 2
        tool_call_message = artifact.messages[1]
        assert "Failed to update" in tool_call_message.content
        assert "new artifact has been created" in tool_call_message.content

    def test_successful_update_returns_update_message(self):
        create_result, create_artifact = async_to_sync(self.tool._arun_impl)(
            title="Original Notebook",
            content="# Original",
        )
        original_artifact_id = create_artifact.messages[1].content.split("artifact_id: ")[1]

        update_result, update_artifact = async_to_sync(self.tool._arun_impl)(
            title="Updated Notebook",
            content="# Updated Content",
            artifact_id=original_artifact_id,
        )

        assert update_result == ""
        assert update_artifact is not None
        tool_call_message = update_artifact.messages[1]
        assert "has been updated" in tool_call_message.content
        assert "Failed" not in tool_call_message.content
