from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync

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

    def _create_visualization_artifact(self, query: dict, short_id: str = "abcd") -> AgentArtifact:
        artifact = AgentArtifact.objects.create(
            team=self.team,
            conversation=self.conversation,
            type=AgentArtifact.Type.VISUALIZATION,
            short_id=short_id,
            name="Chart",
            data={"content_type": "visualization", "query": query, "name": "Chart"},
        )
        return artifact

    def _create_notebook_parent(self, short_id: str = "nbk1") -> AgentArtifact:
        return AgentArtifact.objects.create(
            team=self.team,
            conversation=self.conversation,
            type=AgentArtifact.Type.NOTEBOOK,
            short_id=short_id,
            name="Notebook",
            data={"content_type": "notebook", "blocks": [], "title": "Notebook"},
        )

    def _save_and_get_notebook(self, viz_short_id: str, parent_short_id: str = "nbk1") -> Notebook:
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

    def test_data_visualization_node_is_not_double_wrapped(self):
        # Regression: a stored DataVisualizationNode artifact must not be
        # rewrapped in InsightVizNode, which produces a structurally invalid
        # InsightVizNode -> DataVisualizationNode shape that crashes /insights/new.
        self._create_visualization_artifact(
            query={
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": "SELECT 1"},
                "display": "ActionsBar",
            },
            short_id="dvn1",
        )

        notebook = self._save_and_get_notebook("dvn1")

        ph_queries = _find_ph_query_nodes(notebook.content)
        self.assertEqual(len(ph_queries), 1)
        stored_query = ph_queries[0]["attrs"]["query"]
        self.assertEqual(stored_query["kind"], "DataVisualizationNode")
        self.assertEqual(stored_query["source"]["kind"], "HogQLQuery")

    def test_hogql_query_is_wrapped_in_data_visualization_node(self):
        self._create_visualization_artifact(
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            short_id="hql1",
        )

        notebook = self._save_and_get_notebook("hql1")

        ph_queries = _find_ph_query_nodes(notebook.content)
        self.assertEqual(len(ph_queries), 1)
        stored_query = ph_queries[0]["attrs"]["query"]
        self.assertEqual(stored_query["kind"], "DataVisualizationNode")
        self.assertEqual(stored_query["source"]["kind"], "HogQLQuery")

    def test_assistant_hogql_query_is_wrapped_in_data_visualization_node(self):
        self._create_visualization_artifact(
            query={"kind": "AssistantHogQLQuery", "query": "SELECT 1"},
            short_id="ahq1",
        )

        notebook = self._save_and_get_notebook("ahq1")

        ph_queries = _find_ph_query_nodes(notebook.content)
        self.assertEqual(len(ph_queries), 1)
        stored_query = ph_queries[0]["attrs"]["query"]
        self.assertEqual(stored_query["kind"], "DataVisualizationNode")
        self.assertEqual(stored_query["source"]["kind"], "AssistantHogQLQuery")

    def test_insight_query_node_is_wrapped_in_insight_viz_node(self):
        self._create_visualization_artifact(
            query={"kind": "TrendsQuery", "series": []},
            short_id="trd1",
        )

        notebook = self._save_and_get_notebook("trd1")

        ph_queries = _find_ph_query_nodes(notebook.content)
        self.assertEqual(len(ph_queries), 1)
        stored_query = ph_queries[0]["attrs"]["query"]
        self.assertEqual(stored_query["kind"], "InsightVizNode")
        self.assertEqual(stored_query["source"]["kind"], "TrendsQuery")
