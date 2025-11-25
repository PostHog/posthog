import uuid
from typing import Literal, Self, cast

import structlog
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantMessage,
    AssistantTool,
    AssistantToolCallMessage,
    AssistantUpdateEvent,
    HumanMessage,
)

from posthog.models import Team, User

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.core.executor import AgentExecutor
from ee.hogai.stream.redis_stream import get_subagent_stream_key
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AgentType, ArtifactRefMessage, AssistantMessageUnion, AssistantState, NodePath
from ee.models import Conversation

logger = structlog.get_logger(__name__)


SUBAGENT_TOOL_PROMPT = """
Use this tool to spin up a dedicated agent that can independently tackle complex, multi-step workflows.

# Available agents and modes they can switch between:
{{agents_prompt}}

{{modes_prompt}}

When using the Agent tool, you must specify an agent_type parameter to select what kind of agent to use.

# When not to use the Agent tool

Avoid using the Agent tool in the following situations, where other tools are faster and more direct:
- If you already know the exact event or entity to search for, use the read_data, read_taxonomy or search tool instead of Agent.

For any task that falls outside the agent behaviors described above, do not use this tool.

# Usage guidelines

- *Parallelize when possible*: when you have multiple independent tasks, start several agents at once in a single message by issuing multiple Agent tool calls in parallel to improve latency and throughput.
- *You see the report, not the raw result*: when an agent finishes, it sends back exactly one message containing its findings. This output is visible only to you (the calling system), not directly to the end user. You are responsible for returning a concise, user-facing summary of the agent’s result.
- *Each agent run is stateless and one-shot*: every invocation is independent, you cannot have a back-and-forth with the agent, and it will not be able to ask you clarifying questions. Your prompt must therefore contain a rich, detailed task description and explicitly specify what information the agent should include in its single final response.
- *Treat the agent’s output as generally reliable*: in most cases you can trust its conclusions, though you may still apply light sanity checks where appropriate.
- *Be explicit about the kind of work*: clearly indicate what you expect out of the agent; the agent does not directly know the user’s intent unless you spell it out.

# Examples
<example>
user: "Please check conversion rates at signup with a breakdown by country and by device type"
assistant: Sure let me create two insights to visualize the conversion funnels
assistant: First let me use the read_taxonomy tool to check for events related to signups
assistant: Good, I've found a signed_up event in the user's taxonomy
assistant: Continues with the data research discovering the $geoip_country_code and $device_type properties, and $pageview event
<commentary>
Since the two insights are independent, you can delegate to two agents in parallel.
</commentary>
assistant: Now let me use the Agent tool twice to launch two agents in parallel
assistant: Uses the Agent tool twice with two specific instructions:
- "Create a funnel from $pageview to signed_up event, with a breakdown by $geoip_country_code property
- "Create a funnel from $pageview to signed_up event, with a breakdown by $device_type property
</example>


<example>
user: "How many users are active in GMT+2"
assistant: First let me use the read_taxonomy tool to check for a timezone event property
assistant: Good, I've found a $geoip_time_zone property in the user's taxonomy
<commentary>
Since the assistant can create the insight autonomously, there is no need to use the Agent tool
</commentary>
assistant: Uses the create_insight tool
</example>
""".strip()


class SubagentExecutor(AgentExecutor):
    """Executor for subagent workflows that uses a tool-specific stream key."""

    def __init__(self, conversation: Conversation, tool_call_id: str, **kwargs):
        super().__init__(conversation, **kwargs)
        self._tool_call_id = tool_call_id
        stream_key = get_subagent_stream_key(conversation.id, tool_call_id)
        self._redis_stream._stream_key = stream_key
        self._workflow_id = f"subagent-{conversation.id}-{tool_call_id}"
        self._can_reconnect = False


class SubagentToolArgs(BaseModel):
    title: str = Field(description="A short title for the task")
    task: str = Field(
        description="A clear, detailed description of the task for the subagent to complete. Include all relevant context and desired outcome."
    )
    agent_type: AgentType = Field(default=AgentType.GENERAL_PURPOSE)


class SubagentTool(MaxTool):
    name: Literal[AssistantTool.AGENT] = AssistantTool.AGENT
    description: str = SUBAGENT_TOOL_PROMPT
    args_schema: type[BaseModel] = SubagentToolArgs

    async def _arun_impl(self, title: str, task: str, agent_type: AgentType) -> tuple[str, ToolMessagesArtifact | None]:
        # Avoid circular import
        from posthog.temporal.ai.chat_agent import ChatAgentWorkflow, ChatAgentWorkflowInputs

        thread_id = self._get_thread_id(self._config)
        if not thread_id:
            # make mypy happy
            raise ValueError("Thread id can't be empty")
        conversation = await self._aget_conversation(thread_id)
        if not conversation:
            raise ValueError("Conversation not found")

        inputs = ChatAgentWorkflowInputs(
            team_id=self._team.id,
            user_id=self._user.id,
            conversation_id=conversation.id,
            stream_key=get_subagent_stream_key(conversation.id, self.tool_call_id),
            message=HumanMessage(content=task).model_dump(),
            trace_id=self._get_trace_id(self._config),
            session_id=self._get_session_id(self._config),
            billing_context=self._context_manager.get_billing_context(),
            agent_type=agent_type,
            use_checkpointer=False,
        )

        executor = SubagentExecutor(
            conversation=conversation,
            tool_call_id=self.tool_call_id,
        )

        final_content = ""

        messages: list[AssistantMessageUnion] = []
        try:
            async for event_type, message in executor.astream(ChatAgentWorkflow, inputs):
                if event_type == AssistantEventType.MESSAGE:
                    # Only parse completed messages
                    if isinstance(message, AssistantGenerationStatusEvent) or not message.id:
                        continue
                    if isinstance(message, AssistantMessage):
                        final_content = message.content
                        if message.tool_calls:
                            for tool_call in message.tool_calls:
                                self.dispatcher.update(content=tool_call)
                    if isinstance(message, ArtifactMessage):
                        artifact_ref_message = ArtifactRefMessage(
                            content_type=ArtifactContentType(message.content.content_type),
                            artifact_id=message.artifact_id,
                            source=message.source,
                        )
                        self.dispatcher.message(artifact_ref_message)
                        messages.append(artifact_ref_message)
                elif event_type == AssistantEventType.UPDATE:
                    self.dispatcher.update(cast(AssistantUpdateEvent, message).content)

        except Exception as e:
            logger.exception("Error running subagent", error=e)
            return f"Error running subagent: {e}", None

        messages = [
            *messages,
            AssistantToolCallMessage(content=final_content, tool_call_id=self.tool_call_id, id=str(uuid.uuid4())),
        ]
        return "", ToolMessagesArtifact(messages=messages)

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        from ee.hogai.chat_agent.agents import CHAT_AGENTS

        agents_prompts_list = []
        modes: dict[str, str] = {}
        for agent_type, agent_description in CHAT_AGENTS.items():
            agents_prompt = f"- Type: {agent_type.value}\n- Description: {agent_description.description}\n"
            if len(agent_description.mode_registry) > 1:
                agents_prompt += "- Available modes: " + ", ".join(agent_description.mode_registry.keys()) + "\n"
                for mode, definition in agent_description.mode_registry.items():
                    modes[mode.value] = definition.mode_description
            agents_prompts_list.append(agents_prompt)

        agents_prompt = "\n\n".join(agents_prompts_list)

        modes_prompt = ""
        if len(modes) > 1:
            modes_prompt = "Modes descriptions:\n"
            for mode_value, description in modes.items():
                modes_prompt += f"- {mode_value}: {description}\n"

        description = format_prompt_string(SUBAGENT_TOOL_PROMPT, agents_prompt=agents_prompt, modes_prompt=modes_prompt)

        return cls(
            team=team,
            user=user,
            state=state,
            node_path=node_path,
            config=config,
            description=description,
            context_manager=context_manager,
        )
