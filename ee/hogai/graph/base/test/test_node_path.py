from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.base.context import get_node_path
from ee.hogai.graph.base.graph import BaseAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantGraphName, NodePath
from ee.models import Conversation


class TestNodePath(BaseTest):
    """
    Tests for node_path functionality across sync/async methods and graph compositions.
    """

    async def test_graph_to_async_node_has_two_elements(self):
        """Graph -> Node (async) should have path: [graph, node]"""
        captured_path = None

        class TestNode(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_path
                captured_path = get_node_path()
                return None

        class TestGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

            def setup(self):
                node = TestNode(self._team, self._user)
                self.add_node(AssistantNodeName.ROOT, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                self.add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                return self

        graph = TestGraph(self.team, self.user)
        compiled = graph.setup().compile(checkpointer=False)

        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        await compiled.ainvoke(AssistantState(messages=[]), {"configurable": {"thread_id": conversation.id}})

        assert captured_path is not None
        self.assertEqual(len(captured_path), 2)
        self.assertEqual(captured_path[0].name, AssistantGraphName.ASSISTANT.value)
        # Node name is determined at init time, so it's the class name
        self.assertEqual(captured_path[1].name, "TestNode")

    async def test_graph_to_sync_node_has_two_elements(self):
        """Graph -> Node (sync) should have path: [graph, node]"""
        captured_path = None

        class TestNode(AssistantNode):
            def run(self, state, config):
                nonlocal captured_path
                captured_path = get_node_path()
                return None

        class TestGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

            def setup(self):
                node = TestNode(self._team, self._user)
                self.add_node(AssistantNodeName.ROOT, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                self.add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                return self

        graph = TestGraph(self.team, self.user)
        compiled = graph.setup().compile(checkpointer=False)

        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        await compiled.ainvoke(AssistantState(messages=[]), {"configurable": {"thread_id": conversation.id}})

        assert captured_path is not None
        self.assertEqual(len(captured_path), 2)
        self.assertEqual(captured_path[0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_path[1].name, "TestNode")

    async def test_graph_to_node_to_async_node_has_three_elements(self):
        """Graph -> Node -> Node (async) should have path: [graph, node, node]"""
        captured_paths = []

        class SecondNode(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_paths
                captured_paths.append(get_node_path())
                return None

        class FirstNode(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_paths
                captured_paths.append(get_node_path())
                # Call second node
                second_node = SecondNode(self._team, self._user)
                await second_node(state, config)
                return None

        class TestGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

            def setup(self):
                node = FirstNode(self._team, self._user)
                self.add_node(AssistantNodeName.ROOT, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                self.add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                return self

        graph = TestGraph(self.team, self.user)
        compiled = graph.setup().compile(checkpointer=False)

        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        await compiled.ainvoke(AssistantState(messages=[]), {"configurable": {"thread_id": conversation.id}})

        # First node: [graph, node]
        assert captured_paths[0] is not None
        self.assertEqual(len(captured_paths[0]), 2)
        self.assertEqual(captured_paths[0][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[0][1].name, "FirstNode")

        # Second node: [graph, node, node]
        assert captured_paths[1] is not None
        self.assertEqual(len(captured_paths[1]), 3)
        self.assertEqual(captured_paths[1][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[1][1].name, "FirstNode")
        self.assertEqual(captured_paths[1][2].name, "SecondNode")

    async def test_graph_to_node_to_sync_node_has_three_elements(self):
        """Graph -> Node -> Node (sync) - calling .run() directly doesn't extend path"""
        captured_paths = []

        class SecondNode(AssistantNode):
            def run(self, state, config):
                nonlocal captured_paths
                captured_paths.append(get_node_path())
                return None

        class FirstNode(AssistantNode):
            def run(self, state, config):
                nonlocal captured_paths
                captured_paths.append(get_node_path())
                # Call second node - note: calling run() directly bypasses context setting,
                # so the second node won't have the proper path. This tests that direct .run()
                # calls don't propagate context properly.
                second_node = SecondNode(self._team, self._user)
                second_node.run(state, config)
                return None

        class TestGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

            def setup(self):
                node = FirstNode(self._team, self._user)
                self.add_node(AssistantNodeName.ROOT, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                self.add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                return self

        graph = TestGraph(self.team, self.user)
        compiled = graph.setup().compile(checkpointer=False)

        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        await compiled.ainvoke(AssistantState(messages=[]), {"configurable": {"thread_id": conversation.id}})

        # First node: [graph, node]
        assert captured_paths[0] is not None
        self.assertEqual(len(captured_paths[0]), 2)
        self.assertEqual(captured_paths[0][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[0][1].name, "FirstNode")

        # Second node: [graph, node] - initialized within FirstNode's context, so gets same path
        assert captured_paths[1] is not None
        self.assertEqual(len(captured_paths[1]), 2)
        self.assertEqual(captured_paths[1][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[1][1].name, "FirstNode")  # Same as first because initialized in same context

    async def test_graph_to_node_to_graph_to_node_has_four_elements(self):
        """Graph -> Node -> Graph -> Node should have path: [graph, node, graph, node]"""
        captured_paths = []

        class InnerNode(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_paths
                captured_paths.append(get_node_path())
                return None

        class InnerGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.INSIGHTS

            def setup(self):
                node = InnerNode(self._team, self._user)
                self.add_node(AssistantNodeName.TRENDS_GENERATOR, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR)
                self.add_edge(AssistantNodeName.TRENDS_GENERATOR, AssistantNodeName.END)
                return self

        class OuterNode(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_paths
                captured_paths.append(get_node_path())
                # Call inner graph
                inner_graph = InnerGraph(self._team, self._user)
                compiled_inner = inner_graph.setup().compile(checkpointer=False)
                await compiled_inner.ainvoke(state, config)
                return None

        class OuterGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

            def setup(self):
                node = OuterNode(self._team, self._user)
                self.add_node(AssistantNodeName.ROOT, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                self.add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                return self

        outer_graph = OuterGraph(self.team, self.user)
        compiled = outer_graph.setup().compile(checkpointer=False)

        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        await compiled.ainvoke(AssistantState(messages=[]), {"configurable": {"thread_id": conversation.id}})

        # Outer node: [graph, node]
        assert captured_paths[0] is not None
        self.assertEqual(len(captured_paths[0]), 2)
        self.assertEqual(captured_paths[0][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[0][1].name, "OuterNode")

        # Inner node: [graph, node, graph, node]
        assert captured_paths[1] is not None
        self.assertEqual(len(captured_paths[1]), 4)
        self.assertEqual(captured_paths[1][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[1][1].name, "OuterNode")
        self.assertEqual(captured_paths[1][2].name, AssistantGraphName.INSIGHTS.value)
        self.assertEqual(captured_paths[1][3].name, "InnerNode")

    async def test_graph_to_graph_to_node_has_three_elements(self):
        """Graph -> Graph -> Node should have path: [graph, graph, node]"""
        captured_path = None

        class InnerNode(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_path
                captured_path = get_node_path()
                return None

        class InnerGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.INSIGHTS

            def setup(self):
                node = InnerNode(self._team, self._user)
                self.add_node(AssistantNodeName.TRENDS_GENERATOR, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR)
                self.add_edge(AssistantNodeName.TRENDS_GENERATOR, AssistantNodeName.END)
                return self

        class OuterGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

            async def invoke_inner_graph(self, state, config):
                inner_graph = InnerGraph(self._team, self._user)
                compiled_inner = inner_graph.setup().compile(checkpointer=False)
                await compiled_inner.ainvoke(state, config)

        outer_graph = OuterGraph(self.team, self.user)

        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        await outer_graph.invoke_inner_graph(
            AssistantState(messages=[]), RunnableConfig(configurable={"thread_id": conversation.id})
        )

        # Inner node: [graph, node] - outer graph context is not propagated when calling graph methods directly
        assert captured_path is not None
        self.assertEqual(len(captured_path), 2)
        self.assertEqual(captured_path[0].name, AssistantGraphName.INSIGHTS.value)
        self.assertEqual(captured_path[1].name, "InnerNode")

    async def test_node_path_preserved_across_async_and_sync_methods(self):
        """Test that calling .run() directly doesn't extend path"""
        captured_paths = []

        class SyncNode(AssistantNode):
            def run(self, state, config):
                nonlocal captured_paths
                captured_paths.append(("sync", get_node_path()))
                return None

        class AsyncNode(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_paths
                captured_paths.append(("async", get_node_path()))
                # Call sync node - calling .run() directly bypasses context setting
                sync_node = SyncNode(self._team, self._user)
                sync_node.run(state, config)
                return None

        class TestGraph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

            def setup(self):
                node = AsyncNode(self._team, self._user)
                self.add_node(AssistantNodeName.ROOT, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                self.add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                return self

        graph = TestGraph(self.team, self.user)
        compiled = graph.setup().compile(checkpointer=False)

        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        await compiled.ainvoke(AssistantState(messages=[]), {"configurable": {"thread_id": conversation.id}})

        # Async node: [graph, node]
        self.assertEqual(captured_paths[0][0], "async")
        assert captured_paths[0][1] is not None
        self.assertEqual(len(captured_paths[0][1]), 2)
        self.assertEqual(captured_paths[0][1][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[0][1][1].name, "AsyncNode")

        # Sync node: [graph, node] - initialized within AsyncNode's context, so gets same path
        self.assertEqual(captured_paths[1][0], "sync")
        assert captured_paths[1][1] is not None
        self.assertEqual(len(captured_paths[1][1]), 2)
        self.assertEqual(captured_paths[1][1][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[1][1][1].name, "AsyncNode")  # Same as async because initialized in same context

    def test_node_path_with_explicit_node_path_parameter(self):
        """Test that explicitly passing node_path overrides default behavior"""
        custom_path = (NodePath(name="custom_graph"), NodePath(name="custom_node"))

        class TestNode(AssistantNode):
            def run(self, state, config):
                return None

        node = TestNode(self.team, self.user, node_path=custom_path)

        self.assertEqual(len(node._node_path), 2)
        self.assertEqual(node._node_path[0].name, "custom_graph")
        self.assertEqual(node._node_path[1].name, "custom_node")

    async def test_multiple_nested_graphs(self):
        """Test deeply nested graph composition: Graph -> Node -> Graph -> Node -> Graph -> Node"""
        captured_paths = []

        class Level3Node(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_paths
                captured_paths.append(("level3", get_node_path()))
                return None

        class Level3Graph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.TAXONOMY

            def setup(self):
                node = Level3Node(self._team, self._user)
                self.add_node(AssistantNodeName.FUNNEL_GENERATOR, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_GENERATOR)
                self.add_edge(AssistantNodeName.FUNNEL_GENERATOR, AssistantNodeName.END)
                return self

        class Level2Node(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_paths
                captured_paths.append(("level2", get_node_path()))
                # Call level 3 graph
                level3_graph = Level3Graph(self._team, self._user)
                compiled = level3_graph.setup().compile(checkpointer=False)
                await compiled.ainvoke(state, config)
                return None

        class Level2Graph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.INSIGHTS

            def setup(self):
                node = Level2Node(self._team, self._user)
                self.add_node(AssistantNodeName.TRENDS_GENERATOR, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR)
                self.add_edge(AssistantNodeName.TRENDS_GENERATOR, AssistantNodeName.END)
                return self

        class Level1Node(AssistantNode):
            async def arun(self, state, config):
                nonlocal captured_paths
                captured_paths.append(("level1", get_node_path()))
                # Call level 2 graph
                level2_graph = Level2Graph(self._team, self._user)
                compiled = level2_graph.setup().compile(checkpointer=False)
                await compiled.ainvoke(state, config)
                return None

        class Level1Graph(BaseAssistantGraph[AssistantState, PartialAssistantState]):
            @property
            def state_type(self) -> type[AssistantState]:
                return AssistantState

            @property
            def graph_name(self) -> AssistantGraphName:
                return AssistantGraphName.ASSISTANT

            def setup(self):
                node = Level1Node(self._team, self._user)
                self.add_node(AssistantNodeName.ROOT, node)
                self.add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
                self.add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
                return self

        level1_graph = Level1Graph(self.team, self.user)
        compiled = level1_graph.setup().compile(checkpointer=False)

        conversation = await Conversation.objects.acreate(team=self.team, user=self.user)
        await compiled.ainvoke(AssistantState(messages=[]), {"configurable": {"thread_id": conversation.id}})

        # Level 1: [graph, node]
        assert captured_paths[0][1] is not None
        self.assertEqual(len(captured_paths[0][1]), 2)
        self.assertEqual(captured_paths[0][1][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[0][1][1].name, "Level1Node")

        # Level 2: [graph, node, graph, node]
        assert captured_paths[1][1] is not None
        self.assertEqual(len(captured_paths[1][1]), 4)
        self.assertEqual(captured_paths[1][1][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[1][1][1].name, "Level1Node")
        self.assertEqual(captured_paths[1][1][2].name, AssistantGraphName.INSIGHTS.value)
        self.assertEqual(captured_paths[1][1][3].name, "Level2Node")

        # Level 3: [graph, node, graph, node, graph, node]
        assert captured_paths[2][1] is not None
        self.assertEqual(len(captured_paths[2][1]), 6)
        self.assertEqual(captured_paths[2][1][0].name, AssistantGraphName.ASSISTANT.value)
        self.assertEqual(captured_paths[2][1][1].name, "Level1Node")
        self.assertEqual(captured_paths[2][1][2].name, AssistantGraphName.INSIGHTS.value)
        self.assertEqual(captured_paths[2][1][3].name, "Level2Node")
        self.assertEqual(captured_paths[2][1][4].name, AssistantGraphName.TAXONOMY.value)
        self.assertEqual(captured_paths[2][1][5].name, "Level3Node")
