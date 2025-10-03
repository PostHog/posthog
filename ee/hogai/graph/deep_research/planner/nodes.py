import logging
from typing import Literal, Optional, cast
from uuid import uuid4

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception
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
    ReasoningMessage,
    VisualizationItem,
)

from posthog.models.notebook import Notebook

from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.deep_research.planner.prompts import (
    ARTIFACTS_READ,
    ARTIFACTS_READ_FAILED,
    DEEP_RESEARCH_PLANNER_PROMPT,
    FINALIZE_RESEARCH_TOOL_RESULT,
    INVALID_ARTIFACT_IDS_TOOL_RESULT,
    NO_TOOL_RESULTS,
    TODO_READ_FAILED,
    TODO_READ_TOOL_RESULT,
    TODO_WRITE_TOOL_RESULT,
    WRITE_RESULT_FAILED_TOOL_RESULT,
    WRITE_RESULT_TOOL_RESULT,
)
from ee.hogai.graph.deep_research.types import (
    DeepResearchIntermediateResult,
    DeepResearchNodeName,
    DeepResearchState,
    PartialDeepResearchState,
)
from ee.hogai.graph.root.tools import CreateInsightTool
from ee.hogai.notebook.notebook_serializer import NotebookSerializer
from ee.hogai.tool import ParallelToolExecution
from ee.hogai.utils.helpers import extract_content_from_ai_message
from ee.hogai.utils.types import WithCommentary
from ee.hogai.utils.types.base import (
    AssistantMessageUnion,
    BaseState,
    BaseStateWithMessages,
    InsightArtifact,
    TodoItem,
    ToolArtifact,
    ToolResult,
)
from ee.hogai.utils.types.composed import MaxNodeName

logger = logging.getLogger(__name__)


class todo_write(WithCommentary):
    """
    Create a new TO-DO list. Returns the most recent TO-DO list after the write.
    """

    todos: list[TodoItem] = Field(description="A step-by-step list of TO-DOs for answering the user's question")


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
    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.PLANNER

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
            # Get the planning notebook from current_run_notebooks (should be the first one)
            if not state.current_run_notebooks:
                raise ValueError("No notebooks found in current run.")

            planning_notebook_id = state.current_run_notebooks[0].notebook_id
            notebook = await Notebook.objects.aget(short_id=planning_notebook_id)
            if not notebook:
                raise ValueError("Notebook not found.")

            serializer = NotebookSerializer()
            notebook_content = ProsemirrorJSONContent.model_validate(notebook.content)
            markdown = serializer.from_json_to_markdown(notebook_content)
            messages = [("human", markdown)]

        prompt = ChatPromptTemplate.from_messages(messages)
        core_tools = [todo_write, todo_read, result_write, finalize_research, artifacts_read]
        available_tools = [CreateInsightTool]
        model = self._get_model(instructions, state.previous_response_id).bind_tools(
            core_tools + available_tools,
            tool_choice="required",
            parallel_tool_calls=True,
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
    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.PLANNER_TOOLS

    async def get_reasoning_message(
        self, input: BaseState, default_message: Optional[str] = None
    ) -> ReasoningMessage | None:
        if not isinstance(input, BaseStateWithMessages):
            return None
        if not input.messages:
            return None
        assert isinstance(input.messages[-1], AssistantMessage)
        tool_calls = input.messages[-1].tool_calls or []
        if len(tool_calls) == 0:
            return None

        # For multiple tool calls, create a combined reasoning message
        reasoning_parts = []
        for tool_call in tool_calls:
            if tool_call.name == "todo_write":
                reasoning_parts.append("Writing todos")
            elif tool_call.name == "todo_read":
                reasoning_parts.append("Reading todos")
            elif tool_call.name == "artifacts_read":
                reasoning_parts.append("Analyzing results")
            elif tool_call.name == "result_write":
                reasoning_parts.append("Writing intermediate results")
            elif tool_call.name == "finalize_research":
                reasoning_parts.append("Finalizing research")

        if reasoning_parts:
            # Join multiple actions with commas and "and" for the last item
            if len(reasoning_parts) == 1:
                return ReasoningMessage(content=reasoning_parts[0])
            elif len(reasoning_parts) == 2:
                return ReasoningMessage(content=f"{reasoning_parts[0]} and {reasoning_parts[1]}")
            else:
                return ReasoningMessage(content=f"{', '.join(reasoning_parts[:-1])}, and {reasoning_parts[-1]}")

        return None

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

        tool_calls = last_message.tool_calls

        # Separate tool calls by category for proper ordering
        todo_write_calls = []
        todo_read_calls = []
        artifacts_read_calls = []
        result_write_calls = []
        finalize_research_calls = []
        execute_tool_calls = []

        for tool_call in tool_calls:
            if tool_call.name == "todo_write":
                todo_write_calls.append(tool_call)
            elif tool_call.name == "todo_read":
                todo_read_calls.append(tool_call)
            elif tool_call.name == "artifacts_read":
                artifacts_read_calls.append(tool_call)
            elif tool_call.name == "result_write":
                result_write_calls.append(tool_call)
            elif tool_call.name == "finalize_research":
                finalize_research_calls.append(tool_call)
            else:
                execute_tool_calls.append(tool_call)

        # Process tool calls in the correct order, respecting dependencies
        messages: list[AssistantMessageUnion] = []

        # 1. Process todo_write and todo_read first (no dependencies)
        for tool_call in todo_write_calls:
            result = await self._handle_todo_write(tool_call, state)
            messages.extend(result.messages or [])
            if result.todos:
                state = DeepResearchState(**{**state.model_dump(), "todos": result.todos})

        for tool_call in todo_read_calls:
            result = await self._handle_todo_read(tool_call, state)
            messages.extend(result.messages or [])

        # 2. Check if tools below require TODOs list
        tools_requiring_todos = artifacts_read_calls + execute_tool_calls + result_write_calls + finalize_research_calls
        if tools_requiring_todos and (not state.todos or len(state.todos) == 0):
            # Return error messages for all tool calls that require TODOs
            for tool_call in tools_requiring_todos:
                messages.append(
                    AssistantToolCallMessage(
                        content=TODO_READ_FAILED,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                )
            return PartialDeepResearchState(messages=messages)

        # 3. Process artifacts_read (requires TODOs)
        for tool_call in artifacts_read_calls:
            result = await self._handle_artifacts_read(tool_call, state)
            messages.extend(result.messages or [])

        # 4. Process execute tools in parallel (requires TODOs)
        if execute_tool_calls:
            result = await self._handle_execute_tools(execute_tool_calls, state, config)
            messages.extend(result.messages or [])
            if result.tool_results:
                state = DeepResearchState(**{**state.model_dump(), "tool_results": result.tool_results})

        # 5. Check if tools below require tool results
        tools_requiring_results = result_write_calls + finalize_research_calls
        if tools_requiring_results and len(state.tool_results) == 0:
            # Return error messages for all tool calls that require tool results
            for tool_call in tools_requiring_results:
                messages.append(
                    AssistantToolCallMessage(
                        content=NO_TOOL_RESULTS,
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                )
            return PartialDeepResearchState(messages=messages)

        # 6. Process result_write and finalize_research (require tool results)
        for tool_call in result_write_calls:
            result = await self._handle_result_write(tool_call, state)
            messages.extend(result.messages or [])

        for tool_call in finalize_research_calls:
            result = await self._handle_finalize_research(tool_call, state)
            messages.extend(result.messages or [])

        # Return all collected messages
        if messages:
            return PartialDeepResearchState(messages=messages)

        # This shouldn't happen if tool_calls is not empty, but handle it gracefully
        raise ValueError("No valid tool calls were processed")

    async def _handle_todo_write(self, tool_call, state: DeepResearchState) -> PartialDeepResearchState:
        """Create or update the TODOs list for research tasks."""
        # Parse and validate todos
        todos = [TodoItem.model_validate(todo) for todo in tool_call.args["todos"]]

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
            formatted_todos = TODO_READ_FAILED

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
        """Read artifacts generated from completed tool calls."""
        # Collect all artifacts from tool results
        artifacts: list[ToolArtifact] = []
        for single_tool_result in state.tool_results:
            artifacts.extend(single_tool_result.artifacts)

        # Format artifacts for display
        if artifacts:
            formatted_artifacts = "\n".join([f"- {artifact.id}: {artifact.content}" for artifact in artifacts])
        else:
            formatted_artifacts = ARTIFACTS_READ_FAILED

        return PartialDeepResearchState(
            messages=[
                AssistantToolCallMessage(
                    content=ARTIFACTS_READ.format(artifacts=formatted_artifacts),
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                ),
            ],
        )

    async def _handle_execute_tools(
        self, tool_calls: list[AssistantToolCall], state: DeepResearchState, config: RunnableConfig
    ) -> PartialDeepResearchState:
        result_messages: list[AssistantMessageUnion] = []

        ToolExecutionClass = ParallelToolExecution(
            team=self._team, user=self._user, write_message_afunc=self._write_message
        )
        try:
            tool_results, tool_execution_message = await ToolExecutionClass.arun(tool_calls, state, config)
        except Exception as e:
            capture_exception(
                e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
            )
            result_messages.extend(
                [
                    AssistantToolCallMessage(
                        content="The tool raised an internal error.",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                        visible=False,
                    )
                    for tool_call in tool_calls
                ]
            )

        if tool_execution_message:
            result_messages.append(tool_execution_message)

        for result in tool_results:
            # NOTE: this accounts for the failed tool results too, content and result.metadata contain information about the failure
            result_messages.append(
                AssistantToolCallMessage(
                    content=self._format_tool_result(result),
                    id=str(uuid4()),
                    tool_call_id=result.id,
                    visible=False,
                )
            )

        return PartialDeepResearchState(
            messages=result_messages,
            tool_results=tool_results,
        )

    def _format_tool_result(self, result: ToolResult) -> str:
        artifact_lines = []
        for artifact in result.artifacts:
            artifact_lines.append(f"- {artifact.tool_call_id}: {artifact.content}")
        artifacts_str = "\n".join(artifact_lines)
        formatted_results = f"{result.content}\nArtifacts:\n{artifacts_str}\n"
        return formatted_results

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
        artifacts: list[ToolArtifact] = []
        for single_tool_result in state.tool_results:
            artifacts.extend(single_tool_result.artifacts)

        # Validate artifact IDs referenced in the result
        existing_ids = {str(artifact.id) for artifact in artifacts}
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

        visualizations = [
            VisualizationItem(query=artifact.content, answer=artifact.query)
            for artifact in selected_artifacts
            if isinstance(artifact, InsightArtifact) and artifact.query
        ]

        return PartialDeepResearchState(
            messages=[
                MultiVisualizationMessage(
                    id=str(uuid4()),
                    visualizations=visualizations,
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

    def router(self, state: DeepResearchState) -> Literal["continue", "end"]:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            raise ValueError("Last message is not an assistant tool message.")
        if last_message.content == FINALIZE_RESEARCH_TOOL_RESULT:
            return "end"
        return "continue"
