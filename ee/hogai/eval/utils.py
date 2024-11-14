import asyncio
import json
from os import path
from typing import Literal

import structlog
from deepeval.dataset import EvaluationDataset
from deepeval.test_case import ConversationalTestCase, LLMTestCase
from pydantic import BaseModel, Field

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils import AssistantNodeName
from posthog.models.team.team import Team
from posthog.schema import HumanMessage, RouterMessage, VisualizationMessage

logger = structlog.get_logger(__name__)


class EvaluationTestCaseMessage(BaseModel):
    query: str
    expected_output: str
    actual_output: str = Field(default="")


class EvaluationTestCase(BaseModel):
    title: str
    messages: list[EvaluationTestCaseMessage]


class CompiledEvaluationTestCase(BaseModel):
    title: str
    messages: list[EvaluationTestCase]


EVAL_DATASETS = {
    AssistantNodeName.TRENDS_PLANNER: "trends_planner.json",
    AssistantNodeName.ROUTER: "router.json",
}


async def build_and_evaluate_graph(node: AssistantNodeName, team: Team, data: EvaluationTestCase):
    builder = AssistantGraph(team).add_edge(AssistantNodeName.START, node)
    generations = []
    prev_messages = []

    if node == AssistantNodeName.TRENDS_PLANNER:
        graph = builder.add_trends_planner(AssistantNodeName.END).compile()
        for message in data.messages:
            human_message = HumanMessage(content=message.query)
            state = await asyncio.to_thread(
                graph.invoke,
                {"messages": [*prev_messages, human_message]},
                config={"recursion_limit": 24},
            )
            plan = state.get("plan") or ""
            generations.append(plan)
            prev_messages.append(human_message)
            prev_messages.append(VisualizationMessage(plan=plan))
    elif node == AssistantNodeName.ROUTER:
        graph = (
            builder.add_start()
            .add_router(path_map={"trends": AssistantNodeName.END, "funnel": AssistantNodeName.END})
            .compile()
        )
        for message in data.messages:
            human_message = HumanMessage(content=message.query)
            state = await asyncio.to_thread(
                graph.invoke,
                {"messages": [*prev_messages, human_message]},
                config={"recursion_limit": 24},
            )
            last_message: RouterMessage = state["messages"][-1]
            generations.append(last_message.content)
            prev_messages.append(human_message)
            prev_messages.append(last_message)
    return generations


def load_test_cases(node: AssistantNodeName, load_compiled=False):
    directory = "compiled_datasets" if load_compiled else "datasets"
    with open(path.join("ee", "hogai", "eval", directory, EVAL_DATASETS[node])) as f:
        data = f.read()
        parsed_json: list[dict] = json.loads(data)
        test_cases = [EvaluationTestCase.model_validate(test_case) for test_case in parsed_json]
    return test_cases


def load_dataset(node: AssistantNodeName, load_filter: Literal["all", "test_case", "conversational_test_case"] = "all"):
    loaded_dataset = load_test_cases(node, load_compiled=True)
    test_cases = []
    for test_case in loaded_dataset:
        turns = [
            LLMTestCase(input=mes.query, actual_output=mes.actual_output, expected_output=mes.expected_output)
            for mes in test_case.messages
        ]
        if len(turns) == 1 and load_filter in ("all", "test_case"):
            test_cases.append(turns[0])
        elif len(turns) > 1 and load_filter in ("all", "conversational_test_case"):
            test_cases.append(ConversationalTestCase(turns=turns))
    return EvaluationDataset(test_cases=test_cases)
