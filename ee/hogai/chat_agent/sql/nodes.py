from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage, DataVisualizationNode, FailureMessage

from posthog.hogql.context import HogQLContext

from ee.hogai.utils.types import AssistantState, PartialAssistantState

from ..schema_generator.nodes import SchemaGenerationException, SchemaGeneratorNode, SchemaGeneratorToolsNode
from .mixins import HogQLGeneratorMixin, SQLSchemaGeneratorOutput
from .prompts import SQL_GENERATION_FAILURE_MESSAGE
from .toolkit import SQL_SCHEMA


class SQLGeneratorNode(HogQLGeneratorMixin, SchemaGeneratorNode[DataVisualizationNode]):
    INSIGHT_NAME = "SQL"
    OUTPUT_MODEL = SQLSchemaGeneratorOutput
    OUTPUT_SCHEMA = SQL_SCHEMA

    hogql_context: HogQLContext

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = await self._construct_system_prompt()
        try:
            return await super()._run_with_prompt(state, prompt, config=config)
        except SchemaGenerationException as e:
            # The LLM exhausted its retries on invalid HogQL. Surface this as a graceful tool
            # response so the calling agent can recover, instead of letting it bubble up to the
            # runner's generic handler and be captured as an unhandled application error.
            return self._handle_generation_failure(state, e)

    def _handle_generation_failure(
        self, state: AssistantState, error: SchemaGenerationException
    ) -> PartialAssistantState:
        tool_call_id = state.root_tool_call_id
        content = SQL_GENERATION_FAILURE_MESSAGE.format(error_message=error.validation_message)
        # Respond to the calling agent when there's a tool call to answer; otherwise emit a
        # FailureMessage so the run still terminates cleanly via the query executor.
        message = (
            AssistantToolCallMessage(content=content, id=str(uuid4()), tool_call_id=tool_call_id)
            if tool_call_id
            else FailureMessage(content=content, id=str(uuid4()))
        )
        return PartialAssistantState(
            messages=[message],
            intermediate_steps=None,
            plan=None,
            rag_context=None,
            root_tool_call_id=None,
            root_tool_insight_plan=None,
            root_tool_insight_type=None,
        )


class SQLGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
