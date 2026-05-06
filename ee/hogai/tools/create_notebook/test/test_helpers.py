from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.notebooks.backend.models import Notebook

from ee.hogai.artifacts.types import StoredBlock, VisualizationRefBlock
from ee.hogai.tools.create_notebook.helpers import save_notebook_to_db
from ee.models.assistant import AgentArtifact, Conversation


def _find_ph_query_nodes(doc: dict) -> list[dict]:
    found: list[dict] = []

    def walk(node: dict) -> None:
        if isinstance(node, dict):
            if node.get("type") == "ph-query":
                found.append(node)
            for child in node.get("content", []) or []:
                walk(child)

    walk(doc)
    return found


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

    def _save_and_get_notebook(self, viz_short_id: str, parent_short_id: str) -> Notebook:
        parent = self._create_notebook_parent(parent_short_id)
        blocks: list[StoredBlock] = [VisualizationRefBlock(artifact_id=viz_short_id, title="Chart")]
        async_to_sync(save_notebook_to_db)(
            team=self.team,
            user=self.user,
            artifact=parent,
            blocks=blocks,
            title="Test Notebook",
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
                "assistant_hogql_query_wrapped_in_dvn",
                "vahq",
                "nahq",
                {"kind": "AssistantHogQLQuery", "query": "SELECT 1"},
                "DataVisualizationNode",
                "AssistantHogQLQuery",
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

        ph_queries = _find_ph_query_nodes(notebook.content)
        self.assertEqual(len(ph_queries), 1)
        stored_query = ph_queries[0]["attrs"]["query"]
        self.assertEqual(stored_query["kind"], expected_kind)
        self.assertEqual(stored_query["source"]["kind"], expected_source_kind)
