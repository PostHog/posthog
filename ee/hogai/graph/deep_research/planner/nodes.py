import logging

from langchain_openai import ChatOpenAI
from ee.hogai.graph.base import AssistantNode
from ee.hogai.notebook.notebook_serializer import NotebookSerializer
from ee.hogai.utils.helpers import extract_content_from_ai_message
from ee.hogai.utils.types import (
    DeepResearchIntermediateResult,
    DeepResearchSingleTaskResult,
    DeepResearchTask,
    DeepResearchTodo,
)
from ee.hogai.graph.deep_research.planner.prompts import (
    ARTIFACTS_READ_FAILED_TOOL_RESULT,
    ARTIFACTS_READ_TOOL_RESULT,
    DEEP_RESEARCH_NOTEBOOK_PLANNING_PROMPT,
    DEEP_RESEARCH_PLANNER_PROMPT,
    EXECUTE_TASKS_TOOL_RESULT,
    FINALIZE_RESEARCH_TOOL_RESULT,
    INSIGHT_TYPES,
    DEEP_RESEARCH_ONBOARDING_PROMPT,
    INVALID_ARTIFACT_IDS_TOOL_RESULT,
    NO_TASKS_RESULTS_TOOL_RESULT,
    DUMMY_EXECUTE_TASKS_PROMPT,
    POSTHOG_CAPABILITIES_PROMPT,
    TODO_READ_FAILED_TOOL_RESULT,
    TODO_READ_TOOL_RESULT,
    TODO_WRITE_TOOL_RESULT,
    WRITE_RESULT_FAILED_TOOL_RESULT,
    WRITE_RESULT_TOOL_RESULT,
)
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from langchain_core.runnables import RunnableConfig
from langchain_core.prompts import ChatPromptTemplate
from typing import Any, Literal, cast
from uuid import uuid4
from posthog.models.notebook import Notebook

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    ToolMessage as LangchainToolMessage,
)
from pydantic import BaseModel, Field

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    HumanMessage,
    JSONContent,
    NotebookUpdateMessage,
    PlanningMessage,
    PlanningStep,
)


logger = logging.getLogger(__name__)


class execute_tasks(BaseModel):
    """
    Execute a batch of work, assigning tasks to assistants. Returns the aggregated results of the tasks.
    """

    tasks: list[DeepResearchTask] = Field(description="The tasks to execute")


class return_execution_results(BaseModel):
    """
    NOTE: this is a placeholder tool to test the entire flow.
    """

    results: list[DeepResearchSingleTaskResult] = Field(description="The results of the execution of a batch of work")


class todo_write(BaseModel):
    """
    Create a new TO-DO list. Returns the most recent TO-DO list after the write.
    """

    todos: list[DeepResearchTodo] = Field(description="A step-by-step list of TO-DOs for answering the user's question")


class todo_read(BaseModel):
    """
    Read the current TO-DO list. Use it when unsure about the current state of the plan.
    """


class result_write(BaseModel):
    """
    Write intermediate results, which will be used to write the final report.
    """

    result: DeepResearchIntermediateResult = Field(description="The intermediate result of a batch of work")


class artifacts_read(BaseModel):
    """
    Read all artifacts. Use it when unsure about the current list of artifacts.
    """


class finalize_research(BaseModel):
    """
    Mark the research as complete.
    """


class DeepResearchOnboardingNode(AssistantNode):
    def should_run_onboarding_at_start(
        self, state: AssistantState
    ) -> Literal["onboarding", "notebook_init", "continue"]:
        if state.messages:
            human_messages = [m for m in state.messages if isinstance(m, HumanMessage)]
            if len(human_messages) > 1:
                if state.notebook_id:
                    return "continue"
                return "notebook_init"
        return "onboarding"

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        # We use instructions with the OpenAI Responses API
        instructions = DEEP_RESEARCH_ONBOARDING_PROMPT.format(
            posthog_capabilities=POSTHOG_CAPABILITIES_PROMPT,
            core_memory=await self._aget_core_memory(),
            insight_types=INSIGHT_TYPES,
        )

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last message is not a human message.")

        # Initial message or follow-up to the planner's questions
        prompt = ChatPromptTemplate.from_messages(
            [
                ("human", last_message.content),
            ]
        )

        chain = prompt | self._get_model(
            {
                "instructions": instructions,
                "previous_response_id": state.deep_research_planner_previous_response_id,
            }
        )
        response = await chain.ainvoke(
            {},
            config,
        )
        response = cast(LangchainAIMessage, response)
        response_id = response.response_metadata["id"]

        content = extract_content_from_ai_message(response)

        return PartialAssistantState(
            messages=[AssistantMessage(content=content, id=str(uuid4()))],
            deep_research_planner_previous_response_id=response_id,
        )

    def _get_model(self, model_kwargs: dict[str, Any] | None = None):
        return MaxChatOpenAI(
            model="o3",
            streaming=True,
            use_responses_api=True,
            max_retries=3,
            user=self._user,
            team=self._team,
            model_kwargs=model_kwargs or {},
            reasoning={
                "effort": "low",  # TODO: set to "medium" once we're ready to test the flow end to end
                "summary": "auto",
            },
        )


class DeepResearchNotebookInitNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        notebook = await Notebook.objects.acreate(
            team=self._team,
            created_by=self._user,
            content={
                "type": "doc",
                "content": [],
            },
        )
        notebook_id = str(notebook.short_id)
        return PartialAssistantState(
            messages=[],
            notebook_id=notebook_id,
        )


class DeepResearchNotebookPlanningNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        # We use instructions with the OpenAI Responses API
        instructions = DEEP_RESEARCH_NOTEBOOK_PLANNING_PROMPT.format(
            posthog_capabilities=POSTHOG_CAPABILITIES_PROMPT,
            core_memory=await self._aget_core_memory(),
            insight_types=INSIGHT_TYPES,
        )

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last message is not a human message.")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("human", last_message.content),
            ]
        )

        chain = prompt | self._get_model(
            {
                "instructions": instructions,
                "previous_response_id": state.deep_research_planner_previous_response_id,
            }
        )
        response = await chain.ainvoke(
            {},
            config,
        )
        response = cast(LangchainAIMessage, response)

        content = extract_content_from_ai_message(response)

        serializer = NotebookSerializer()
        title = None
        json_content = serializer.from_markdown_to_json(content)
        if json_content.content:
            try:
                next_heading = next(node for node in json_content.content if node.type == "heading")
                if next_heading:
                    title = next_heading.content[0].text if next_heading.content else None
            except StopIteration:
                title = None
        notebook = await Notebook.objects.aget(short_id=state.notebook_id)
        if not notebook:
            raise ValueError("Notebook not found.")

        # save content to file
        # TODO: this is for debugging, remove this before merging
        with open("notebook_content.md", "w") as f:
            f.write(content)
        with open("notebook_content.json", "w") as f:
            f.write(json_content.model_dump_json(exclude_none=True))
        notebook.title = title or "Deep Research Plan"
        notebook_id = str(notebook.short_id)
        notebook.content = json_content.model_dump(exclude_none=True)
        await notebook.asave()

        return PartialAssistantState(
            messages=[
                NotebookUpdateMessage(
                    id=str(uuid4()), notebook_id=notebook_id, content=JSONContent.model_validate(notebook.content)
                )
            ],
            deep_research_planner_previous_response_id=None,  # we reset the previous response id because we're starting a new conversation after the onboarding
            notebook_id=notebook_id,
        )

    def _get_model(self, model_kwargs: dict[str, Any] | None = None):
        return MaxChatOpenAI(
            model="o3",
            streaming=True,
            use_responses_api=True,
            max_retries=3,
            user=self._user,
            team=self._team,
            model_kwargs=model_kwargs or {},
            reasoning={
                "effort": "low",  # TODO: set to "medium" once we're ready to test the flow end to end
                "summary": "auto",
            },
        )


class DeepResearchPlannerNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        # We use instructions with the OpenAI Responses API
        instructions = DEEP_RESEARCH_PLANNER_PROMPT.format(
            posthog_capabilities=POSTHOG_CAPABILITIES_PROMPT,
            core_memory=await self._aget_core_memory(),
            insight_types=INSIGHT_TYPES,
        )

        messages = []
        if state.deep_research_planner_previous_response_id:
            last_message = state.messages[-1]
            if isinstance(last_message, HumanMessage):
                # We're resuming a conversation after the user canceled the conversation
                other_messages = [m for m in state.messages if not isinstance(m, HumanMessage)]
                last_other_message = other_messages[-1]
                if isinstance(last_other_message, AssistantMessage) and last_other_message.tool_calls:
                    messages.append(
                        [
                            LangchainToolMessage(
                                content="The tool call was interrupted by the user.", tool_call_id=tool_call.id
                            )
                            for tool_call in last_other_message.tool_calls
                        ]
                    )
                elif isinstance(last_other_message, AssistantToolCallMessage):
                    messages.append(
                        LangchainToolMessage(
                            content=last_other_message.content, tool_call_id=last_other_message.tool_call_id
                        )
                    )
                messages.append(("human", last_message.content))
            elif isinstance(last_message, AssistantToolCallMessage):
                messages.append(
                    LangchainToolMessage(content=last_message.content, tool_call_id=last_message.tool_call_id)
                )
            else:
                raise ValueError("Unexpected message type.")
        else:
            notebook = await Notebook.objects.aget(short_id=state.notebook_id)
            if not notebook:
                raise ValueError("Notebook not found.")

            serializer = NotebookSerializer()
            notebook_content = JSONContent.model_validate(notebook.content)
            markdown = serializer.from_json_to_markdown(notebook_content)
            messages = [("human", markdown)]

        prompt = ChatPromptTemplate.from_messages(messages)

        chain = prompt | self._get_model(
            {
                "instructions": instructions,
                "previous_response_id": state.deep_research_planner_previous_response_id,
            }
        )
        response = await chain.ainvoke(
            {},
            config,
        )
        response = cast(LangchainAIMessage, response)

        content = extract_content_from_ai_message(response)
        response_id = response.response_metadata["id"]

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=content,
                    tool_calls=[
                        AssistantToolCall(id=tool_call["id"], name=tool_call["name"], args=tool_call["args"])
                        for tool_call in response.tool_calls
                    ],
                    id=str(uuid4()),
                ),
            ],
            deep_research_planner_previous_response_id=response_id,
        )

    def _get_model(self, model_kwargs: dict[str, Any] | None = None):
        model = MaxChatOpenAI(
            model="o3",
            streaming=True,
            use_responses_api=True,
            max_retries=3,
            user=self._user,
            team=self._team,
            model_kwargs=model_kwargs or {},
            reasoning={
                "effort": "low",  # TODO: set to "medium" once we're ready to test the flow end to end
                "summary": "auto",
            },
        )
        return model.bind_tools([todo_write, todo_read, result_write, finalize_research])

    def router(self, state: AssistantState) -> Literal["continue", "end"]:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage):
            raise ValueError("Last message is not an assistant message.")
        tool_calls = last_message.tool_calls
        if tool_calls:
            return "continue"
        return "end"


class DeepResearchPlannerToolsNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage):
            raise ValueError("Last message is not an assistant message.")

        tool_calls = last_message.tool_calls
        if not tool_calls:
            raise ValueError("No tool calls found in the last message.")

        if len(tool_calls) != 1:
            raise ValueError("Expected exactly one tool call.")

        tool_call = tool_calls[0]
        if tool_call.name == "todo_write":
            todos = [DeepResearchTodo.model_validate(todo) for todo in tool_call.args["todos"]]
            return PartialAssistantState(
                messages=[
                    PlanningMessage(
                        id=str(uuid4()),
                        steps=[
                            PlanningStep(
                                description=todo.description,
                                status=todo.status,
                            )
                            for todo in todos
                        ],
                    ),
                    AssistantToolCallMessage(
                        content=TODO_WRITE_TOOL_RESULT.format(todos=todos),
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
                todos=todos,
            )
        elif tool_call.name == "todo_read":
            formatted_todos = (
                {"todos": [todo.model_dump_json() for todo in state.todos]}
                if len(state.todos) > 0
                else TODO_READ_FAILED_TOOL_RESULT
            )
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=TODO_READ_TOOL_RESULT.format(todos=formatted_todos),
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        # Tools below this point require a TO-DO list
        if len(state.todos) == 0:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=TODO_READ_FAILED_TOOL_RESULT,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        if tool_call.name == "artifacts_read":
            artifacts = []
            for result in state.task_results:
                artifacts.extend(result.artifacts)
            formatted_artifacts = (
                "\n".join([f"- {artifact.short_id}: {artifact.description}" for artifact in artifacts])
                if len(artifacts) > 0
                else ARTIFACTS_READ_FAILED_TOOL_RESULT
            )
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=ARTIFACTS_READ_TOOL_RESULT.format(artifacts=formatted_artifacts),
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        if tool_call.name == "execute_tasks":
            # TODO: replace with the Task Execution Agent, this is a dummy implementation to test the entire flow
            tasks = tool_call.args["tasks"]
            model = ChatOpenAI(model="gpt-4.1-nano", streaming=False).bind_tools([return_execution_results])
            formatted_tasks = "\n".join([f"- {task.description}: {task.prompt}" for task in tasks])
            prompt = DUMMY_EXECUTE_TASKS_PROMPT.format(tasks=formatted_tasks)
            chain = (
                ChatPromptTemplate.from_messages(
                    [
                        ("human", prompt),
                    ]
                )
                | model
            )
            response = await chain.ainvoke(
                {},
                config,
            )
            response = cast(LangchainAIMessage, response)
            tool_calls = response.tool_calls
            if not tool_calls:
                raise ValueError("No tool calls found in the response.")
            tool_call = tool_calls[0]
            results = [DeepResearchSingleTaskResult.model_validate(result) for result in tool_call["args"]["results"]]
            formatted_results = ""
            for result in results:
                artifact_lines = []
                for artifact in result.artifacts:
                    artifact_lines.append(f"- {artifact.short_id}: {artifact.description}")
                artifacts_str = "\n".join(artifact_lines)
                formatted_results += f"- {result.description}:\n{result.result}\nArtifacts:\n{artifacts_str}\n"
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=EXECUTE_TASKS_TOOL_RESULT.format(results=formatted_results),
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
                task_results=results,
            )

        # Tools below this point require a task results
        if len(state.task_results) == 0:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=NO_TASKS_RESULTS_TOOL_RESULT,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        if tool_call.name == "result_write":
            result = tool_call.args["result"]
            result_content = result["content"]
            if len(result_content) == 0:
                return PartialAssistantState(
                    messages=[
                        AssistantToolCallMessage(
                            content=WRITE_RESULT_FAILED_TOOL_RESULT,
                            id=str(uuid4()),
                            tool_call_id=tool_call.id,
                        ),
                    ],
                )
            result_artifact_ids = result.get("artifact_short_ids", [])

            artifacts = []
            for result in state.task_results:
                artifacts.extend(result.artifacts)
            existing_artifact_short_ids = [artifact.short_id for artifact in artifacts]
            invalid_artifact_ids = set(result_artifact_ids) - set(existing_artifact_short_ids)
            if invalid_artifact_ids:
                return PartialAssistantState(
                    messages=[
                        AssistantToolCallMessage(
                            content=INVALID_ARTIFACT_IDS_TOOL_RESULT.format(invalid_artifact_ids=invalid_artifact_ids),
                            id=str(uuid4()),
                            tool_call_id=tool_call.id,
                        ),
                    ],
                )
            new_intermediate_result = DeepResearchIntermediateResult.model_validate(result)
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=WRITE_RESULT_TOOL_RESULT,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
                intermediate_results=[new_intermediate_result],
            )
        elif tool_call.name == "finalize_research":
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=FINALIZE_RESEARCH_TOOL_RESULT, id=str(uuid4()), tool_call_id=tool_call.id
                    ),
                ],
            )
        else:
            raise ValueError(f"Unknown tool call: {tool_call.name}")
