#!/usr/bin/env python3
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph, StateGraph, START, END

from github import Repository
from .state import AgentState
from .nodes import DetectFrameworkNode, RetrieveFilesNode, FilterFilesNode, GenerateFileChangeNode, CommitFilesNode, CreatePRNode

def create_graph(repo: Repository.Repository) -> CompiledStateGraph:

    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("retrieve_files", lambda s: RetrieveFilesNode(repo).run(s))

    graph_builder.add_node("detect_framework", lambda s: DetectFrameworkNode().run(s))

    graph_builder.add_node("filter_files", lambda s: FilterFilesNode().run(s))

    def generate_file_changes(state: AgentState) -> AgentState:
        for file_path in state.get("relevant_files", []):
            state = GenerateFileChangeNode(repo).run(state, file_path)
        return state

    graph_builder.add_node("commit_changes", lambda s: CommitFilesNode(repo).run(s))
    graph_builder.add_node("generate_file_changes", generate_file_changes)
    graph_builder.add_node("create_pr", lambda s: CreatePRNode(repo).run(s))

    graph_builder.add_edge(START, "retrieve_files")
    graph_builder.add_edge("retrieve_files", "detect_framework")
    graph_builder.add_edge("detect_framework", "filter_files")
    graph_builder.add_edge("filter_files", "generate_file_changes")
    graph_builder.add_edge("generate_file_changes", "commit_changes")
    graph_builder.add_edge("commit_changes", "create_pr")
    graph_builder.add_edge("create_pr", END)


    checkpointer = MemorySaver()

    graph = graph_builder.compile(checkpointer=checkpointer)

    return graph
