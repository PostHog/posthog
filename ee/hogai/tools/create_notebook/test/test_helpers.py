import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.schema import TrendsQuery, VisualizationMessage

from products.notebooks.backend.facade.collab import apply_utf16_text_changes, markdown_crc
from products.notebooks.backend.models import Notebook
from products.posthog_ai.backend.models.assistant import AgentArtifact, Conversation

from ee.hogai.artifacts.types import StoredBlock, VisualizationRefBlock
from ee.hogai.tools.create_notebook.helpers import NotebookEditNotAllowedError, save_notebook_to_db


def _get_notebook_markdown(notebook: Notebook) -> str:
    nodes = notebook.content["content"]
    assert len(nodes) == 1 and nodes[0]["type"] == "ph-markdown-notebook"
    return nodes[0]["attrs"]["markdown"]


def _extract_query_props(markdown: str) -> list[dict]:
    """Pull the JSON `query={...}` props out of serialized `<Query ... />` tags."""
    queries: list[dict] = []
    search_from = 0
    while (start := markdown.find("query={", search_from)) != -1:
        json_start = start + len("query={")
        depth = 1
        i = json_start
        while i < len(markdown) and depth:
            char = markdown[i]
            if char == '"':
                # Skip over JSON strings so braces inside them don't affect depth
                i += 1
                while i < len(markdown) and (markdown[i] != '"' or markdown[i - 1] == "\\"):
                    i += 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            i += 1
        queries.append(json.loads(markdown[json_start : i - 1]))
        search_from = i
    return queries


class TestSaveNotebookToDb(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

    def _create_visualization_artifact(self, query: dict, short_id: str) -> AgentArtifact:
        return AgentArtifact.objects.create(
            team=self.team,
            conversation=self.conversation,
            type=AgentArtifact.Type.VISUALIZATION,
            short_id=short_id,
            name="Chart",
            data={"content_type": "visualization", "query": query, "name": "Chart"},
        )

    def _create_notebook_parent(self, short_id: str) -> AgentArtifact:
        return AgentArtifact.objects.create(
            team=self.team,
            conversation=self.conversation,
            type=AgentArtifact.Type.NOTEBOOK,
            short_id=short_id,
            name="Notebook",
            data={"content_type": "notebook", "blocks": [], "title": "Notebook"},
        )

    def _save_and_get_notebook(
        self,
        viz_short_id: str,
        parent_short_id: str,
        state_messages: list | None = None,
    ) -> Notebook:
        parent = self._create_notebook_parent(parent_short_id)
        blocks: list[StoredBlock] = [VisualizationRefBlock(artifact_id=viz_short_id, title="Chart")]
        async_to_sync(save_notebook_to_db)(
            team=self.team,
            user=self.user,
            artifact=parent,
            blocks=blocks,
            title="Test Notebook",
            state_messages=state_messages or [],
        )
        return Notebook.objects.get(team=self.team, short_id=parent.short_id)

    @parameterized.expand(
        [
            (
                "data_visualization_node_passthrough",
                "vdvn",
                "ndvn",
                {
                    "kind": "DataVisualizationNode",
                    "source": {"kind": "HogQLQuery", "query": "SELECT 1"},
                    "display": "ActionsBar",
                },
                "DataVisualizationNode",
                "HogQLQuery",
            ),
            (
                "hogql_query_wrapped_in_dvn",
                "vhql",
                "nhql",
                {"kind": "HogQLQuery", "query": "SELECT 1"},
                "DataVisualizationNode",
                "HogQLQuery",
            ),
            (
                "insight_query_wrapped_in_insight_viz_node",
                "vtrd",
                "ntrd",
                {"kind": "TrendsQuery", "series": []},
                "InsightVizNode",
                "TrendsQuery",
            ),
        ]
    )
    def test_save_notebook_to_db_wraps_query_correctly(
        self,
        _case_name: str,
        viz_short_id: str,
        parent_short_id: str,
        artifact_query: dict,
        expected_kind: str,
        expected_source_kind: str,
    ):
        self._create_visualization_artifact(query=artifact_query, short_id=viz_short_id)

        notebook = self._save_and_get_notebook(viz_short_id, parent_short_id)

        queries = _extract_query_props(_get_notebook_markdown(notebook))
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["kind"], expected_kind)
        self.assertEqual(queries[0]["source"]["kind"], expected_source_kind)

    def test_save_notebook_resolves_state_only_visualization(self):
        # Reproduces the "[Visualization not found: <id>]" bug: viz exists only in
        # conversation state (as a VisualizationMessage), not in AgentArtifact.
        viz_short_id = "vstt"
        viz_message = VisualizationMessage(
            id=viz_short_id,
            answer=TrendsQuery(series=[]),
        )

        notebook = self._save_and_get_notebook(
            viz_short_id,
            "nstt",
            state_messages=[viz_message],
        )

        queries = _extract_query_props(_get_notebook_markdown(notebook))
        self.assertEqual(len(queries), 1, "state-only viz should resolve to a query block")
        self.assertEqual(queries[0]["kind"], "InsightVizNode")
        self.assertEqual(queries[0]["source"]["kind"], "TrendsQuery")

    def test_save_notebook_emits_placeholder_when_artifact_missing(self):
        # Sanity: when the ref can't be resolved from any source, we still get the
        # "[Visualization not found]" placeholder paragraph instead of a ph-query.
        notebook = self._save_and_get_notebook(
            viz_short_id="vmis",
            parent_short_id="nmis",
        )

        markdown = _get_notebook_markdown(notebook)
        self.assertEqual(len(_extract_query_props(markdown)), 0)
        self.assertIn("Visualization not found", markdown)

    def test_save_notebook_creates_markdown_notebook(self):
        self._create_visualization_artifact(query={"kind": "TrendsQuery", "series": []}, short_id="vmkd")
        parent = self._create_notebook_parent("nmkd")
        blocks: list[StoredBlock] = [VisualizationRefBlock(artifact_id="vmkd", title="Chart")]

        async_to_sync(save_notebook_to_db)(
            team=self.team,
            user=self.user,
            artifact=parent,
            blocks=blocks,
            title="Test Notebook",
            state_messages=[],
        )

        notebook = Notebook.objects.get(team=self.team, short_id=parent.short_id)
        nodes = notebook.content["content"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["type"], "ph-markdown-notebook")
        markdown = nodes[0]["attrs"]["markdown"]
        self.assertIn("Test Notebook", markdown)
        self.assertIn("<Query", markdown)
        self.assertIn("InsightVizNode", markdown)
        self.assertEqual(notebook.text_content, markdown)

    def test_save_notebook_keeps_tiptap_format_for_existing_notebook(self):
        parent = self._create_notebook_parent("ntfm")
        notebook = Notebook.objects.create(
            team=self.team,
            short_id=parent.short_id,
            title="Original title",
            created_by=self.user,
            last_modified_by=self.user,
            content={"type": "doc", "content": [{"type": "paragraph"}]},
        )

        with patch("ee.hogai.tools.create_notebook.helpers.collab.apublish_notebook_update"):
            async_to_sync(save_notebook_to_db)(
                team=self.team,
                user=self.user,
                artifact=parent,
                blocks=[],
                title="Updated title",
                state_messages=[],
                markdown_content="# Updated",
            )

        notebook.refresh_from_db()
        self.assertEqual(notebook.title, "Updated title")
        self.assertNotEqual(notebook.content["content"][0]["type"], "ph-markdown-notebook")

    def test_save_notebook_preserves_existing_markdown_v2_wrapper(self):
        parent = self._create_notebook_parent("nv2m")
        notebook = Notebook.objects.create(
            team=self.team,
            short_id=parent.short_id,
            title="Original title",
            created_by=self.user,
            last_modified_by=self.user,
            content={
                "type": "doc",
                "content": [
                    {
                        "type": "ph-markdown-notebook",
                        "attrs": {
                            "nodeId": "custom-node-id",
                            "markdown": "# Original",
                        },
                    }
                ],
            },
        )
        original_version = notebook.version
        original_last_modified_at = notebook.last_modified_at

        with patch("ee.hogai.tools.create_notebook.helpers.collab.apublish_notebook_update") as mock_publish:
            async_to_sync(save_notebook_to_db)(
                team=self.team,
                user=self.user,
                artifact=parent,
                blocks=[],
                title="Updated title",
                state_messages=[],
                markdown_content="# Updated\n\nAdd this here.",
            )

        notebook.refresh_from_db()
        mock_publish.assert_awaited_once()
        assert mock_publish.await_args is not None
        publish_args, publish_kwargs = mock_publish.await_args
        self.assertEqual(publish_args, (self.team.id, str(parent.short_id), original_version + 1))
        # Receivers replay the diff instead of refetching; it must transform the old markdown exactly
        diff = publish_kwargs["diff"]
        self.assertEqual(diff.base_crc, markdown_crc("# Original"))
        self.assertEqual(apply_utf16_text_changes("# Original", diff.changes), "# Updated\n\nAdd this here.")
        self.assertEqual(notebook.title, "Updated title")
        self.assertEqual(notebook.text_content, "# Updated\n\nAdd this here.")
        self.assertEqual(notebook.version, original_version + 1)
        self.assertGreater(notebook.last_modified_at, original_last_modified_at)
        self.assertEqual(
            notebook.content,
            {
                "type": "doc",
                "content": [
                    {
                        "type": "ph-markdown-notebook",
                        "attrs": {
                            "nodeId": "custom-node-id",
                            "markdown": "# Updated\n\nAdd this here.",
                        },
                    }
                ],
            },
        )

    def test_save_notebook_update_advances_version_and_publishes_update(self):
        parent = self._create_notebook_parent("nvrs")
        notebook = Notebook.objects.create(
            team=self.team,
            short_id=parent.short_id,
            title="Original title",
            created_by=self.user,
            last_modified_by=self.user,
            content={"type": "doc", "content": [{"type": "paragraph"}]},
        )
        original_version = notebook.version

        with patch("ee.hogai.tools.create_notebook.helpers.collab.apublish_notebook_update") as mock_publish:
            async_to_sync(save_notebook_to_db)(
                team=self.team,
                user=self.user,
                artifact=parent,
                blocks=[],
                title="Updated title",
                state_messages=[],
            )

        notebook.refresh_from_db()
        self.assertEqual(notebook.version, original_version + 1)
        mock_publish.assert_awaited_once_with(self.team.id, str(parent.short_id), original_version + 1)

    def test_save_rejected_without_editor_access_on_existing_notebook(self):
        from posthog.constants import AvailableFeature
        from posthog.models import OrganizationMembership, User

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        creator = User.objects.create_and_join(self.organization, "notebook-owner@posthog.com", None)
        parent = self._create_notebook_parent("nacc")
        notebook = Notebook.objects.create(
            team=self.team,
            short_id=parent.short_id,
            title="Protected title",
            created_by=creator,
            last_modified_by=creator,
            content={"type": "doc", "content": [{"type": "paragraph"}]},
        )
        AccessControl.objects.create(
            team=self.team, resource="notebook", resource_id=str(notebook.id), access_level="viewer"
        )

        with self.assertRaises(NotebookEditNotAllowedError):
            async_to_sync(save_notebook_to_db)(
                team=self.team,
                user=self.user,
                artifact=parent,
                blocks=[],
                title="Overwritten title",
                state_messages=[],
            )

        notebook.refresh_from_db()
        self.assertEqual(notebook.title, "Protected title")
