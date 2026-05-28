from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig

from posthog.schema import HumanMessage, MaxNotebookContext, MaxUIContext

from products.notebooks.backend.models import Notebook

from ee.hogai.context import AssistantContextManager
from ee.hogai.tools.edit_notebook import EditNotebookTool, EditNotebookToolArgs, ReplaceTextEdit, build_edit_plan
from ee.hogai.utils.types.base import AssistantState, NodePath
from ee.models.assistant import AgentArtifact, Conversation


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _hogql_node(code: str, title: str = "Recent events", return_variable: str = "events_df") -> dict:
    return {
        "type": "ph-hogql-sql",
        "attrs": {
            "code": code,
            "returnVariable": return_variable,
            "title": title,
            "__init": {"showSettings": True},
        },
    }


def test_build_edit_plan_replace_text_updates_document_content():
    plan = build_edit_plan(
        {"type": "doc", "content": [_paragraph("replace this text")]},
        [ReplaceTextEdit(find="this", replace="that")],
        {},
    )

    assert plan.content == {"type": "doc", "content": [_paragraph("replace that text")]}
    assert plan.steps == [
        {"stepType": "replace", "from": 9, "to": 13, "slice": {"content": [{"type": "text", "text": "that"}]}}
    ]
    assert plan.text_content == "replace that text"


def test_build_edit_plan_inserts_analysis_cells_from_markdown():
    plan = build_edit_plan(
        {"type": "doc", "content": [_paragraph("Start here")]},
        [
            EditNotebookToolArgs.model_validate(
                {
                    "edits": [
                        {
                            "type": "insert_after",
                            "anchor": "Start here",
                            "content": '<hogql title="Recent events" return_variable="events_df">\nSELECT * FROM events LIMIT 10\n</hogql>',
                        }
                    ]
                }
            ).edits[0]
        ],
        {},
    )

    assert plan.content["content"][1] == {
        "type": "ph-hogql-sql",
        "attrs": {
            "code": "SELECT * FROM events LIMIT 10",
            "returnVariable": "events_df",
            "title": "Recent events",
            "__init": {"showSettings": True},
        },
    }
    assert (
        plan.text_content
        == 'Start here\n<hogql title="Recent events" return_variable="events_df">\nSELECT * FROM events LIMIT 10\n</hogql>'
    )


def test_build_edit_plan_replaces_existing_analysis_cell_by_title():
    plan = build_edit_plan(
        {"type": "doc", "content": [_hogql_node("SELECT * FROM events LIMIT 10")]},
        [
            EditNotebookToolArgs.model_validate(
                {
                    "edits": [
                        {
                            "type": "replace_block",
                            "anchor": "Recent events",
                            "content": '<python title="Summarize">\nprint(events_df.head())\n</python>',
                        }
                    ]
                }
            ).edits[0]
        ],
        {},
    )

    assert plan.content["content"] == [
        {
            "type": "ph-python",
            "attrs": {
                "code": "print(events_df.head())",
                "title": "Summarize",
                "__init": {"showSettings": True},
            },
        }
    ]
    assert plan.steps == [
        {
            "stepType": "replace",
            "from": 0,
            "to": 1,
            "slice": {
                "content": [
                    {
                        "type": "ph-python",
                        "attrs": {
                            "code": "print(events_df.head())",
                            "title": "Summarize",
                            "__init": {"showSettings": True},
                        },
                    }
                ]
            },
        }
    ]
    assert plan.text_content == '<python title="Summarize">\nprint(events_df.head())\n</python>'


class TestEditNotebookTool(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        self.context_manager = AssistantContextManager(self.team, self.user, self.config)
        self.tool_call_id = "test_tool_call_id"
        self.node_path = (NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),)

    def _tool(self, state: AssistantState | None = None) -> EditNotebookTool:
        return EditNotebookTool(
            team=self.team,
            user=self.user,
            state=state or AssistantState(messages=[]),
            config=self.config,
            context_manager=self.context_manager,
            node_path=self.node_path,
        )

    def _create_notebook(self, short_id: str = "editnb1") -> Notebook:
        return Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            last_modified_by=self.user,
            short_id=short_id,
            title="Original notebook",
            content={
                "type": "doc",
                "content": [
                    {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Notebook"}]},
                    _paragraph("This is not a local notebook\n\nreplace this block with active users"),
                    _paragraph("Keep this paragraph"),
                ],
            },
            text_content="Notebook\nThis is not a local notebook\nreplace this block with active users\nKeep this paragraph",
        )

    def test_replace_block_inserts_visualization_artifact_through_collab(self):
        notebook = self._create_notebook()
        AgentArtifact.objects.create(
            team=self.team,
            conversation=self.conversation,
            short_id="viz1",
            name="Active users",
            type=AgentArtifact.Type.VISUALIZATION,
            data={
                "content_type": "visualization",
                "name": "Active users",
                "query": {"kind": "TrendsQuery", "series": []},
            },
        )
        args = EditNotebookToolArgs.model_validate(
            {
                "short_id": notebook.short_id,
                "edits": [
                    {
                        "type": "replace_block",
                        "anchor": "replace this block with active users",
                        "content": "<insight>viz1</insight>",
                    }
                ],
            }
        )

        result, artifact = async_to_sync(self._tool()._arun_impl)(short_id=args.short_id, edits=args.edits)

        assert result == f"Updated notebook {notebook.short_id} with 1 edit."
        assert artifact == {"short_id": notebook.short_id, "applied_edits": 1}

        notebook.refresh_from_db()
        assert notebook.version == 1
        content = notebook.content["content"]
        assert content[1]["type"] == "ph-query"
        assert content[1]["attrs"]["title"] == "Active users"
        assert content[1]["attrs"]["query"] == {
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": []},
        }
        assert content[2] == _paragraph("Keep this paragraph")

    def test_uses_single_notebook_from_ui_context_when_short_id_omitted(self):
        notebook = self._create_notebook(short_id="ctxnb1")
        state = AssistantState(
            messages=[
                HumanMessage(
                    id="human-1",
                    content="add a note",
                    ui_context=MaxUIContext(notebooks=[MaxNotebookContext(id=notebook.short_id, name=notebook.title)]),
                )
            ],
            start_id="human-1",
        )
        args = EditNotebookToolArgs.model_validate(
            {"edits": [{"type": "append", "content": "Added by AI", "content_format": "plain_text"}]}
        )

        result, artifact = async_to_sync(self._tool(state)._arun_impl)(edits=args.edits)

        assert result == f"Updated notebook {notebook.short_id} with 1 edit."
        assert artifact == {"short_id": notebook.short_id, "applied_edits": 1}
        notebook.refresh_from_db()
        assert notebook.content["content"][-1] == _paragraph("Added by AI")

    def test_requires_short_id_when_no_single_notebook_context(self):
        args = EditNotebookToolArgs.model_validate(
            {"edits": [{"type": "append", "content": "Added by AI", "content_format": "plain_text"}]}
        )

        result, artifact = async_to_sync(self._tool()._arun_impl)(edits=args.edits)

        assert (
            result
            == "Error: No notebook short_id was provided, and there is not exactly one notebook in the current context."
        )
        assert artifact is None

    @patch("ee.hogai.tools.edit_notebook.has_notebook_python_feature_flag", return_value=False)
    def test_rejects_executable_analysis_cells_without_feature_flag(self, _mock_flag):
        notebook = self._create_notebook()
        args = EditNotebookToolArgs.model_validate(
            {
                "short_id": notebook.short_id,
                "edits": [{"type": "append", "content": "<hogql>\nSELECT 1\n</hogql>"}],
            }
        )

        result, artifact = async_to_sync(self._tool()._arun_impl)(short_id=args.short_id, edits=args.edits)

        assert "notebook-python feature flag" in result
        assert artifact is None
        notebook.refresh_from_db()
        assert notebook.version == 0
