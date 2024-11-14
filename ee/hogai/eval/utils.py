import asyncio
from typing import TypedDict

import structlog

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils import AssistantNodeName
from posthog.models.team.team import Team
from posthog.schema import HumanMessage

logger = structlog.get_logger(__name__)


class EvaluationTestCase(TypedDict):
    title: str
    query: str
    expected_output: str


class GeneratedEvaluationTestCase(EvaluationTestCase):
    actual_output: str


EVAL_DATASETS = {
    AssistantNodeName.TRENDS_PLANNER: "trends_planner.json",
}


async def build_and_evaluate_graph(node: AssistantNodeName, team: Team, data: EvaluationTestCase):
    builder = AssistantGraph(team).add_edge(AssistantNodeName.START, node)
    if node == AssistantNodeName.TRENDS_PLANNER:
        builder.add_trends_planner(AssistantNodeName.END)
    graph = builder.compile()
    res = await asyncio.to_thread(
        graph.invoke,
        {"messages": [HumanMessage(content=data["query"])]},
        config={"recursion_limit": 24},
    )
    return res.get("plan") or ""
