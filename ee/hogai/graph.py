from langgraph.graph.state import StateGraph

from ee.hogai.trends.nodes import CreateTrendsPlanNode, CreateTrendsPlanToolsNode, GenerateTrendsNode
from ee.hogai.utils import AssistantNodeName, AssistantState

builder = StateGraph(AssistantState)

builder.add_node(AssistantNodeName.CREATE_TRENDS_PLAN, CreateTrendsPlanNode.run)
builder.add_node(AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS, CreateTrendsPlanToolsNode.run)
builder.add_node(AssistantNodeName.GENERATE_TRENDS, GenerateTrendsNode.run)
builder.add_edge(AssistantNodeName.START, AssistantNodeName.CREATE_TRENDS_PLAN)
builder.add_edge(AssistantNodeName.CREATE_TRENDS_PLAN, AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS)
builder.add_edge(AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS, AssistantNodeName.CREATE_TRENDS_PLAN)
builder.add_edge(AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS, AssistantNodeName.GENERATE_TRENDS)

builder.add_edge(AssistantNodeName.GENERATE_TRENDS, AssistantNodeName.END)

assistant_graph = builder.compile()
