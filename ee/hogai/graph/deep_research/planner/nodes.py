import logging
from typing import Literal, cast
from uuid import uuid4

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import Field

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    HumanMessage,
    MultiVisualizationMessage,
    PlanningMessage,
    PlanningStep,
    ProsemirrorJSONContent,
    VisualizationItem,
)

from posthog.models.notebook import Notebook

from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.deep_research.planner.prompts import (
    ARTIFACTS_READ_FAILED_TOOL_RESULT,
    ARTIFACTS_READ_TOOL_RESULT,
    DEEP_RESEARCH_PLANNER_PROMPT,
    FINALIZE_RESEARCH_TOOL_RESULT,
    INVALID_ARTIFACT_IDS_TOOL_RESULT,
    NO_TASKS_RESULTS_TOOL_RESULT,
    TODO_READ_FAILED_TOOL_RESULT,
    TODO_READ_TOOL_RESULT,
    TODO_WRITE_TOOL_RESULT,
    WRITE_RESULT_FAILED_TOOL_RESULT,
    WRITE_RESULT_TOOL_RESULT,
)
from ee.hogai.graph.deep_research.types import (
    DeepResearchIntermediateResult,
    DeepResearchState,
    DeepResearchTodo,
    InsightArtifact,
    PartialDeepResearchState,
    TaskExecutionItem,
)
from ee.hogai.notebook.notebook_serializer import NotebookSerializer
from ee.hogai.utils.helpers import extract_content_from_ai_message
from ee.hogai.utils.types import WithCommentary

logger = logging.getLogger(__name__)


class execute_tasks(WithCommentary):
    """
    Execute a batch of work, assigning tasks to assistants. Returns the aggregated results of the tasks.
    """

    tasks: list[TaskExecutionItem] = Field(description="The tasks to execute")


class todo_write(WithCommentary):
    """
    Create a new TO-DO list. Returns the most recent TO-DO list after the write.
    """

    todos: list[DeepResearchTodo] = Field(description="A step-by-step list of TO-DOs for answering the user's question")


class todo_read(WithCommentary):
    """
    Read the current TO-DO list. Use it when unsure about the current state of the plan.
    """


class result_write(WithCommentary):
    """
    Write intermediate results, which will be used to write the final report.
    """

    result: DeepResearchIntermediateResult = Field(description="The intermediate result of a batch of work")


class artifacts_read(WithCommentary):
    """
    Read all artifacts. Use it when unsure about the current list of artifacts.
    """


class finalize_research(WithCommentary):
    """
    Mark the research as complete.
    """


class DeepResearchPlannerNode(DeepResearchNode):
    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        # We use instructions with the OpenAI Responses API
        instructions = DEEP_RESEARCH_PLANNER_PROMPT.format(
            core_memory=await self._aget_core_memory(),
        )

        messages: list[tuple[str, str] | LangchainToolMessage] = []
        if state.previous_response_id:
            last_message = state.messages[-1]
            if isinstance(last_message, HumanMessage):
                # We're resuming a conversation after the user canceled the conversation
                other_messages = [m for m in state.messages if not isinstance(m, HumanMessage)]
                if len(other_messages) == 0:
                    raise ValueError("No other messages found in the state.")
                last_other_message = other_messages[-1]
                if isinstance(last_other_message, AssistantMessage) and last_other_message.tool_calls:
                    messages.extend(
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
            notebook = await Notebook.objects.aget(short_id=state.notebook_short_id)
            if not notebook:
                raise ValueError("Notebook not found.")

            serializer = NotebookSerializer()
            notebook_content = ProsemirrorJSONContent.model_validate(notebook.content)
            markdown = serializer.from_json_to_markdown(notebook_content)
            messages = [("human", markdown)]

        prompt = ChatPromptTemplate.from_messages(messages)
        model = self._get_model(instructions, state.previous_response_id).bind_tools(
            [todo_write, todo_read, result_write, finalize_research, artifacts_read, execute_tasks],
            tool_choice="required",
        )

        chain = prompt | model
        response = await chain.ainvoke(
            {},
            config,
        )
        response = cast(LangchainAIMessage, response)

        content = extract_content_from_ai_message(response)
        response_id = response.response_metadata["id"]

        tool_calls = response.tool_calls
        if len(tool_calls) > 1:
            raise ValueError("Expected exactly one tool call.")
        commentary = tool_calls[0]["args"].get("commentary")
        _messages = [AssistantMessage(content=commentary, id=str(uuid4()))] if commentary else []
        return PartialDeepResearchState(
            messages=[
                *_messages,
                AssistantMessage(
                    content=content,
                    tool_calls=[
                        AssistantToolCall(id=cast(str, tool_call["id"]), name=tool_call["name"], args=tool_call["args"])
                        for tool_call in response.tool_calls
                    ],
                    id=str(uuid4()),
                ),
            ],
            previous_response_id=response_id,
        )


class DeepResearchPlannerToolsNode(DeepResearchNode):
    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage):
            raise ValueError("Last message is not an assistant message.")

        if not last_message.tool_calls:
            return PartialDeepResearchState(
                messages=[
                    HumanMessage(
                        content="You have to use at least one tool to continue.",
                        id=str(uuid4()),
                    ),
                ],
            )

        if len(last_message.tool_calls) != 1:
            raise ValueError("Expected exactly one tool call.")

        tool_call = last_message.tool_calls[0]
        tool_call_name = tool_call.name

        if tool_call_name == "todo_write":
            return await self._handle_todo_write(tool_call, state)
        elif tool_call_name == "todo_read":
            return await self._handle_todo_read(tool_call, state)

        # Toold below this point require a TODOs list
        if not state.todos or len(state.todos) == 0:
            return PartialDeepResearchState(
                messages=[
                    AssistantToolCallMessage(
                        content=TODO_READ_FAILED_TOOL_RESULT,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        if tool_call_name == "artifacts_read":
            return await self._handle_artifacts_read(tool_call, state)
        elif tool_call_name == "execute_tasks":
            return await self._handle_execute_tasks(tool_call, state)

        # Tools below this point require task results
        if len(state.task_results) == 0:
            return PartialDeepResearchState(
                messages=[
                    AssistantToolCallMessage(
                        content=NO_TASKS_RESULTS_TOOL_RESULT,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        if tool_call_name == "result_write":
            return await self._handle_result_write(tool_call, state)
        elif tool_call_name == "finalize_research":
            return await self._handle_finalize_research(tool_call, state)

        raise ValueError(f"Unknown tool call: {tool_call.name}")

    async def _handle_todo_write(self, tool_call, state: DeepResearchState) -> PartialDeepResearchState:
        """Create or update the TODOs list for research tasks."""
        # Parse and validate todos
        todos = [DeepResearchTodo.model_validate(todo) for todo in tool_call.args["todos"]]

        if not todos:
            return PartialDeepResearchState(
                messages=[
                    AssistantToolCallMessage(
                        content="You have to provide at least one TO-DO.",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        # Format todos for display
        formatted_todos = "\n".join(
            [f"- {todo.description}: {todo.status} (priority: {todo.priority})" for todo in todos]
        )

        # Return planning message with todos
        return PartialDeepResearchState(
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
                    content=TODO_WRITE_TOOL_RESULT.format(todos=formatted_todos),
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                ),
            ],
            todos=todos,
        )

    async def _handle_todo_read(self, tool_call, state: DeepResearchState) -> PartialDeepResearchState:
        """Read and return the current TODO list."""
        if state.todos and len(state.todos) > 0:
            formatted_todos = "\n".join(
                [f"- {todo.description}: {todo.status} (priority: {todo.priority})" for todo in state.todos]
            )
        else:
            formatted_todos = TODO_READ_FAILED_TOOL_RESULT

        return PartialDeepResearchState(
            messages=[
                AssistantToolCallMessage(
                    content=TODO_READ_TOOL_RESULT.format(todos=formatted_todos),
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                ),
            ],
        )

    async def _handle_artifacts_read(self, tool_call, state: DeepResearchState) -> PartialDeepResearchState:
        """Read artifacts generated from completed tasks."""
        # Collect all artifacts from task results
        artifacts: list[InsightArtifact] = []
        for single_task_result in state.task_results:
            artifacts.extend(single_task_result.artifacts)

        # Format artifacts for display
        if artifacts:
            formatted_artifacts = "\n".join([f"- {artifact.id}: {artifact.description}" for artifact in artifacts])
        else:
            formatted_artifacts = ARTIFACTS_READ_FAILED_TOOL_RESULT

        return PartialDeepResearchState(
            messages=[
                AssistantToolCallMessage(
                    content=ARTIFACTS_READ_TOOL_RESULT.format(artifacts=formatted_artifacts),
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                ),
            ],
        )

    async def _handle_execute_tasks(self, tool_call, state: DeepResearchState) -> PartialDeepResearchState:
        """Execute tasks from the TODOs list."""
        # Simply pass the tasks to be executed
        return PartialDeepResearchState(
            tasks=tool_call.args["tasks"],
        )

    async def _handle_result_write(self, tool_call, state: DeepResearchState) -> PartialDeepResearchState:
        """Write intermediate results with selected artifacts."""
        # Parse the intermediate result
        intermediate_result = DeepResearchIntermediateResult.model_validate(tool_call.args["result"])

        if not intermediate_result.content:
            return PartialDeepResearchState(
                messages=[
                    AssistantToolCallMessage(
                        content=WRITE_RESULT_FAILED_TOOL_RESULT,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        # Collect all available artifacts
        artifacts: list[InsightArtifact] = []
        for single_task_result in state.task_results:
            artifacts.extend(single_task_result.artifacts)

        # Validate artifact IDs referenced in the result
        existing_ids = {artifact.id for artifact in artifacts}
        invalid_ids = set(intermediate_result.artifact_ids) - existing_ids

        if invalid_ids:
            return PartialDeepResearchState(
                messages=[
                    AssistantToolCallMessage(
                        content=INVALID_ARTIFACT_IDS_TOOL_RESULT.format(invalid_artifact_ids=invalid_ids),
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                ],
            )

        # Create visualization messages from selected artifacts
        selected_artifacts = [artifact for artifact in artifacts if artifact.id in intermediate_result.artifact_ids]

        visualization_messages = [
            VisualizationItem(query=artifact.description, answer=artifact.query)
            for artifact in selected_artifacts
            if artifact.query
        ]

        return PartialDeepResearchState(
            messages=[
                MultiVisualizationMessage(
                    id=str(uuid4()),
                    visualizations=visualization_messages,
                    commentary=intermediate_result.content,
                ),
                AssistantToolCallMessage(
                    content=WRITE_RESULT_TOOL_RESULT,
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                ),
            ],
            intermediate_results=[intermediate_result],
        )

    async def _handle_finalize_research(self, tool_call, state: DeepResearchState) -> PartialDeepResearchState:
        """Finalize the research and prepare for report generation."""
        return PartialDeepResearchState(
            messages=[
                AssistantToolCallMessage(
                    content=FINALIZE_RESEARCH_TOOL_RESULT,
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                ),
            ],
        )

    def router(self, state: DeepResearchState) -> Literal["continue", "end", "task_executor"]:
        if state.tasks and len(state.tasks) > 0:
            return "task_executor"
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            raise ValueError("Last message is not an assistant tool message.")
        if last_message.content == FINALIZE_RESEARCH_TOOL_RESULT:
            return "end"
        return "continue"
