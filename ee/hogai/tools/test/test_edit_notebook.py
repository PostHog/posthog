from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig

from posthog.schema import HumanMessage, MaxNotebookContext, MaxUIContext

from products.notebooks.backend.models import Notebook

from ee.hogai.context import AssistantContextManager
from ee.hogai.context.notebook.prompts import ROOT_NOTEBOOKS_CONTEXT_PROMPT
from ee.hogai.tools.edit_notebook import (
    EDIT_NOTEBOOK_PROMPT,
    EditNotebookTool,
    EditNotebookToolArgs,
    ReplaceTextEdit,
    build_edit_notebook_prompt,
    build_edit_plan,
)
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


def _query_node(query: dict, title: str = "Query") -> dict:
    return {"type": "ph-query", "attrs": {"query": query, "title": title}}


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


def test_build_edit_plan_replace_text_uses_utf16_offsets_after_non_bmp_text():
    plan = build_edit_plan(
        {"type": "doc", "content": [_paragraph("😀 replace this text")]},
        [ReplaceTextEdit(find="this", replace="that")],
        {},
    )

    assert plan.content == {"type": "doc", "content": [_paragraph("😀 replace that text")]}
    assert plan.steps == [
        {"stepType": "replace", "from": 12, "to": 16, "slice": {"content": [{"type": "text", "text": "that"}]}}
    ]


def test_build_edit_plan_text_positions_use_utf16_node_sizes():
    plan = build_edit_plan(
        {"type": "doc", "content": [_paragraph("😀"), _paragraph("target text")]},
        [ReplaceTextEdit(find="target", replace="updated")],
        {},
    )

    assert plan.content == {"type": "doc", "content": [_paragraph("😀"), _paragraph("updated text")]}
    assert plan.steps == [
        {"stepType": "replace", "from": 5, "to": 11, "slice": {"content": [{"type": "text", "text": "updated"}]}}
    ]


def test_build_edit_plan_replace_text_all_occurrences_does_not_rematch_replacement_text():
    plan = build_edit_plan(
        {"type": "doc", "content": [_paragraph("http http")]},
        [ReplaceTextEdit(find="http", replace="https", all_occurrences=True)],
        {},
    )

    assert plan.content == {"type": "doc", "content": [_paragraph("https https")]}
    assert plan.steps == [
        {"stepType": "replace", "from": 1, "to": 5, "slice": {"content": [{"type": "text", "text": "https"}]}},
        {"stepType": "replace", "from": 7, "to": 11, "slice": {"content": [{"type": "text", "text": "https"}]}},
    ]


def test_build_edit_plan_replace_text_updates_query_node_by_title_anchor():
    old_query = {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "SELECT event\nFROM events\nLIMIT 25"},
        "display": "ActionsTable",
    }
    new_query = {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "SELECT event\nFROM events\nLIMIT 200"},
        "display": "ActionsTable",
    }

    plan = build_edit_plan(
        {"type": "doc", "content": [_query_node(old_query, "Referring domain by segment")]},
        [ReplaceTextEdit(anchor="Referring domain by segment", find="LIMIT 25", replace="LIMIT 200")],
        {},
    )

    assert plan.content == {"type": "doc", "content": [_query_node(new_query, "Referring domain by segment")]}
    assert plan.steps == [
        {
            "stepType": "replace",
            "from": 0,
            "to": 1,
            "slice": {"content": [_query_node(new_query, "Referring domain by segment")]},
        }
    ]


def test_build_edit_plan_replace_text_all_occurrences_does_not_rematch_query_attribute_replacements():
    old_query = {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "SELECT 'http' AS url\nUNION ALL SELECT 'http'"},
        "display": "ActionsTable",
    }
    new_query = {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "SELECT 'https' AS url\nUNION ALL SELECT 'https'"},
        "display": "ActionsTable",
    }

    plan = build_edit_plan(
        {"type": "doc", "content": [_query_node(old_query, "URLs")]},
        [ReplaceTextEdit(find="http", replace="https", all_occurrences=True)],
        {},
    )

    assert plan.content == {"type": "doc", "content": [_query_node(new_query, "URLs")]}
    assert plan.steps == [
        {
            "stepType": "replace",
            "from": 0,
            "to": 1,
            "slice": {"content": [_query_node(new_query, "URLs")]},
        }
    ]


def test_build_edit_plan_replace_text_uses_heading_anchor_as_section_range():
    old_query = {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "SELECT event\nFROM events\nLIMIT 25"},
        "display": "ActionsTable",
    }
    new_query = {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "SELECT event\nFROM events\nLIMIT 200"},
        "display": "ActionsTable",
    }
    other_query = {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "SELECT * FROM events LIMIT 25"},
        "display": "ActionsTable",
    }

    plan = build_edit_plan(
        {
            "type": "doc",
            "content": [
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Referrer analysis"}]},
                _paragraph("This section compares referrers."),
                _query_node(old_query, "Referring domain by segment"),
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Entry path analysis"}],
                },
                _query_node(other_query, "Entry path by segment"),
            ],
        },
        [ReplaceTextEdit(anchor="Referrer analysis", find="LIMIT 25", replace="LIMIT 200")],
        {},
    )

    assert plan.content["content"] == [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Referrer analysis"}]},
        _paragraph("This section compares referrers."),
        _query_node(new_query, "Referring domain by segment"),
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Entry path analysis"}]},
        _query_node(other_query, "Entry path by segment"),
    ]


def test_replace_text_schema_and_prompt_teach_query_edit_fast_path():
    schema = ReplaceTextEdit.model_json_schema()

    assert "SQL inside query" in schema["properties"]["find"]["description"]
    assert "heading" in schema["properties"]["anchor"]["description"]
    assert "small SQL edits" in EDIT_NOTEBOOK_PROMPT
    assert "small SQL edits" in build_edit_notebook_prompt(allow_executable_analysis_blocks=True)


def test_notebook_prompts_do_not_advertise_executable_cell_tags_without_feature_flag():
    executable_prompt = build_edit_notebook_prompt(allow_executable_analysis_blocks=True)

    for prompt in (ROOT_NOTEBOOKS_CONTEXT_PROMPT, EDIT_NOTEBOOK_PROMPT):
        assert "<hogql" not in prompt
        assert "<ducksql" not in prompt
        assert "<python" not in prompt

    assert "<hogql" in executable_prompt
    assert "<ducksql" in executable_prompt
    assert "<python" in executable_prompt


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
        allow_executable_analysis_blocks=True,
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
        allow_executable_analysis_blocks=True,
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
