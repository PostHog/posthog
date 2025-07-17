import json
import logging
from typing import cast
from collections.abc import Sequence
from ee.hogai.graph.deep_research.agent_subgraph.prompts import (
    AGENT_INTERMEDIATE_SUMMARY_PROMPT,
    AGENT_RESEARCH_PREVIOUS_TODO_RESULT_PROMPT,
    AGENT_RESEARCH_PROMPT,
)
from langchain_openai import ChatOpenAI
from ee.hogai.graph.deep_research.base import DeepResearchNode
from ee.hogai.graph.deep_research.serializer import DeepResearchSerializer
from ee.hogai.utils.types import AssistantMessageUnion, AssistantMode, AssistantState, PartialAssistantState
from langchain_core.runnables import RunnableConfig
from langchain_core.prompts import ChatPromptTemplate
import xml.etree.ElementTree as ET
from uuid import uuid4
from langgraph.config import get_stream_writer

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
)

from ee.models.assistant import Conversation
from posthog.models.notebook.notebook import Notebook
from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
    VisualizationMessage,
)

logger = logging.getLogger(__name__)


class DeepResearchAgentSubgraphNode(DeepResearchNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        from ee.hogai.assistant import Assistant

        deep_research_plan = state.deep_research_plan
        if not deep_research_plan:
            raise ValueError("No deep research plan found.")
        next_todo = next(todo for todo in deep_research_plan.todos if todo.status == "pending")
        todo_id = next_todo.short_id

        previous_todo_result = None
        todo_index = deep_research_plan.todos.index(next_todo)
        previous_todo_index = todo_index - 1
        if previous_todo_index >= 0:
            previous_todo = deep_research_plan.todos[previous_todo_index]
            if previous_todo.status == "completed" and previous_todo.requires_result_from_previous_todo:
                previous_todo_result = deep_research_plan.results.get(previous_todo.short_id, None)

        message = AGENT_RESEARCH_PROMPT.format(title=next_todo.short_description, instructions=next_todo.instructions)
        if previous_todo_result:
            message += AGENT_RESEARCH_PREVIOUS_TODO_RESULT_PROMPT.format(previous_todo_result=previous_todo_result)

        conversation = await Conversation.objects.acreate(
            team=self._team,
            user=self._user,
            internal=True,
        )
        agent = Assistant(
            self._team,
            conversation,
            new_message=HumanMessage(content=message),
            user=self._user,
            is_new_conversation=True,
            trace_id=str(uuid4()),
            mode=AssistantMode.ASSISTANT,
        )

        writer = get_stream_writer()
        async for chunk in agent.astream():
            writer(chunk)

        agent_state = agent._state
        if not agent_state:
            raise ValueError("No state found.")
        messages = agent_state.messages

        has_failure_message = any(isinstance(message, FailureMessage) for message in messages)
        markdown_result = None
        if not has_failure_message:
            formatted_messages, insights_map = self._format_conversation_messages(messages)

            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", AGENT_INTERMEDIATE_SUMMARY_PROMPT),
                ],
                template_format="mustache",
            )

            chain = prompt | self._get_model(state, config)

            message = await chain.ainvoke(
                {"conversation": formatted_messages},
                config,
            )
            message = cast(LangchainAIMessage, message)
            if not state.notebook:
                raise ValueError("No notebook found.")
            notebook_serializer = DeepResearchSerializer()
            notebook = await Notebook.objects.aget(short_id=state.notebook)
            _, markdown_result = await notebook_serializer.save_to_notebook(
                notebook, str(message.content), insights_map
            )

        todos = []
        success = markdown_result is not None and not has_failure_message
        for todo in deep_research_plan.todos:
            if todo.short_id == todo_id:
                todo.status = "completed" if success else "failed"
                break
            todos.append(todo)
        deep_research_plan.todos = todos
        if success:
            deep_research_plan.results[todo_id] = cast(str, markdown_result)
        else:
            deep_research_plan.results[todo_id] = "Inconclusive, the agent could not complete the task."

        await self._save_deep_research_plan(deep_research_plan, config)

        return PartialAssistantState(
            deep_research_plan=deep_research_plan,
        )

    def _format_conversation_messages(self, messages: Sequence[AssistantMessageUnion]) -> tuple[str, dict[str, str]]:
        insights_map = {}
        root = ET.Element("messages")
        for message in messages:
            if isinstance(message, AssistantMessage):
                message_tag = ET.SubElement(root, "assistant_message")
                content_tag = ET.SubElement(message_tag, "content")
                content_tag.text = message.content
                if message.tool_calls:
                    tool_calls_tag = ET.SubElement(message_tag, "tool_calls")
                    for tool_call in message.tool_calls:
                        tool_call_tag = ET.SubElement(tool_calls_tag, "tool_call")
                        tool_call_tag.set("id", tool_call.id)
                        tool_call_tag.set("name", tool_call.name)
                        tool_call_tag.set("args", json.dumps(tool_call.args))
            elif isinstance(message, HumanMessage):
                message_tag = ET.SubElement(root, "human_message")
                content_tag = ET.SubElement(message_tag, "content")
                content_tag.text = message.content
            elif isinstance(message, AssistantToolCallMessage):
                message_tag = ET.SubElement(root, "tool_result")
                content_tag = ET.SubElement(message_tag, "content")
                content_tag.text = message.content
                id_tag = ET.SubElement(message_tag, "id")
                id_tag.text = message.id
            elif isinstance(message, FailureMessage):
                message_tag = ET.SubElement(root, "failure_message")
                content_tag = ET.SubElement(message_tag, "content")
                content_tag.text = message.content
            elif isinstance(message, VisualizationMessage):
                if not message.id or not message.query:
                    continue
                insights_map[message.id] = message.query
                message_tag = ET.SubElement(root, "visualization_message")
                id_tag = ET.SubElement(message_tag, "visualization_id")
                id_tag.text = message.id
                query_tag = ET.SubElement(message_tag, "query")
                query_tag.text = message.query
                if message.plan:
                    plan_tag = ET.SubElement(message_tag, "instructions")
                    plan_tag.text = message.plan
                insights_map[message.id] = message.query
        return ET.tostring(root, encoding="unicode"), insights_map

    def _get_model(self, state: AssistantState, config: RunnableConfig):
        return ChatOpenAI(model="o4-mini", streaming=True, stream_usage=True, max_retries=3)
