import xml.etree.ElementTree as ET
from collections.abc import Sequence
from functools import cached_property
from typing import Generic, Optional, TypeVar
from uuid import uuid4

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    AIMessage as LangchainAssistantMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    merge_message_runs,
)
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from ee.hogai.schema_generator.parsers import (
    PydanticOutputParserException,
    parse_pydantic_structured_output,
)
from ee.hogai.schema_generator.prompts import (
    FAILOVER_OUTPUT_PROMPT,
    FAILOVER_PROMPT,
    GROUP_MAPPING_PROMPT,
    NEW_PLAN_PROMPT,
    PLAN_PROMPT,
    QUESTION_PROMPT,
)
from ee.hogai.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.utils.helpers import find_last_message_of_type, slice_messages_to_conversation_start
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantMessageUnion, AssistantState, PartialAssistantState
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import (
    AssistantMessage,
    FailureMessage,
    HumanMessage,
    VisualizationMessage,
)

Q = TypeVar("Q", bound=BaseModel)


class SchemaGeneratorNode(AssistantNode, Generic[Q]):
    INSIGHT_NAME: str
    """
    Name of the insight type used in the exception messages.
    """
    OUTPUT_MODEL: type[SchemaGeneratorOutput[Q]]
    """Pydantic model of the output to be generated by the LLM."""
    OUTPUT_SCHEMA: dict
    """JSON schema of OUTPUT_MODEL for LLM's use."""

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0, disable_streaming=True).with_structured_output(
            self.OUTPUT_SCHEMA,
            method="function_calling",
            include_raw=False,
        )

    @classmethod
    def parse_output(cls, output: dict) -> Optional[SchemaGeneratorOutput[Q]]:
        try:
            return cls.OUTPUT_MODEL.model_validate(output)
        except ValidationError:
            return None

    def _run_with_prompt(
        self,
        state: AssistantState,
        prompt: ChatPromptTemplate,
        config: Optional[RunnableConfig] = None,
    ) -> PartialAssistantState:
        start_id = state.start_id
        generated_plan = state.plan or ""
        intermediate_steps = state.intermediate_steps or []
        validation_error_message = intermediate_steps[-1][1] if intermediate_steps else None

        generation_prompt = prompt + self._construct_messages(state, validation_error_message=validation_error_message)
        merger = merge_message_runs()
        parser = parse_pydantic_structured_output(self.OUTPUT_MODEL)

        chain = generation_prompt | merger | self._model | parser

        try:
            message: SchemaGeneratorOutput[Q] = chain.invoke({}, config)
        except PydanticOutputParserException as e:
            # Generation step is expensive. After a second unsuccessful attempt, it's better to send a failure message.
            if len(intermediate_steps) >= 2:
                return PartialAssistantState(
                    messages=[
                        FailureMessage(
                            content=f"Oops! It looks like I’m having trouble generating this {self.INSIGHT_NAME} insight. Could you please try again?"
                        )
                    ],
                    intermediate_steps=[],
                    plan="",
                )

            return PartialAssistantState(
                intermediate_steps=[
                    *intermediate_steps,
                    (AgentAction("handle_incorrect_response", e.llm_output, e.validation_message), None),
                ],
            )

        final_message = VisualizationMessage(
            plan=generated_plan,
            answer=message.query,
            initiator=start_id,
            id=str(uuid4()),
        )

        return PartialAssistantState(
            messages=[final_message],
            intermediate_steps=[],
            plan="",
        )

    def router(self, state: AssistantState):
        if state.intermediate_steps:
            return "tools"
        return "next"

    @cached_property
    def _group_mapping_prompt(self) -> str:
        groups = GroupTypeMapping.objects.filter(project_id=self._team.project_id).order_by("group_type_index")
        if not groups:
            return "The user has not defined any groups."

        root = ET.Element("list of defined groups")
        root.text = (
            "\n" + "\n".join([f'name "{group.group_type}", index {group.group_type_index}' for group in groups]) + "\n"
        )
        return ET.tostring(root, encoding="unicode")

    def _get_human_viz_message_mapping(self, messages: Sequence[AssistantMessageUnion]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for idx, msg in enumerate(messages):
            if isinstance(msg, VisualizationMessage) and msg.initiator is not None:
                mapping[msg.initiator] = idx
        return mapping

    def _construct_messages(
        self, state: AssistantState, validation_error_message: Optional[str] = None
    ) -> list[BaseMessage]:
        """
        Reconstruct the conversation for the generation. Take all previously generated questions, plans, and schemas, and return the history.
        """
        messages = state.messages
        generated_plan = state.plan
        start_id = state.start_id

        if start_id is not None:
            messages = slice_messages_to_conversation_start(messages, start_id)
        if len(messages) == 0:
            return []

        conversation: list[BaseMessage] = [
            HumanMessagePromptTemplate.from_template(GROUP_MAPPING_PROMPT, template_format="mustache").format(
                group_mapping=self._group_mapping_prompt
            )
        ]

        msg_mapping = self._get_human_viz_message_mapping(messages)
        initiator_message = messages[-1]
        last_viz_message = find_last_message_of_type(messages, VisualizationMessage)

        for message in messages:
            # The initial human message and the new plan are added to the end of the conversation.
            if message == initiator_message:
                continue
            if isinstance(message, HumanMessage):
                if message.id and (viz_message_idx := msg_mapping.get(message.id)):
                    # Plans go first.
                    viz_message = messages[viz_message_idx]
                    if isinstance(viz_message, VisualizationMessage):
                        conversation.append(
                            HumanMessagePromptTemplate.from_template(PLAN_PROMPT, template_format="mustache").format(
                                plan=viz_message.plan or ""
                            )
                        )

                    # Augment with the prompt previous initiator messages.
                    conversation.append(
                        HumanMessagePromptTemplate.from_template(QUESTION_PROMPT, template_format="mustache").format(
                            question=message.content
                        )
                    )
                # Otherwise, just append the human message.
                else:
                    conversation.append(LangchainHumanMessage(content=message.content))
            # Summary, human-in-the-loop messages.
            elif isinstance(message, AssistantMessage):
                conversation.append(LangchainAssistantMessage(content=message.content))

        # Include only last generated schema because it doesn't need more context.
        if last_viz_message:
            conversation.append(
                LangchainAssistantMessage(
                    content=last_viz_message.answer.model_dump_json() if last_viz_message.answer else ""
                )
            )
        # Add the initiator message and the generated plan to the end, so instructions are clear.
        if isinstance(initiator_message, HumanMessage):
            if generated_plan:
                plan_prompt = PLAN_PROMPT if messages[0] == initiator_message else NEW_PLAN_PROMPT
                conversation.append(
                    HumanMessagePromptTemplate.from_template(plan_prompt, template_format="mustache").format(
                        plan=generated_plan or ""
                    )
                )
            conversation.append(
                HumanMessagePromptTemplate.from_template(QUESTION_PROMPT, template_format="mustache").format(
                    question=initiator_message.content
                )
            )

        # Retries must be added to the end of the conversation.
        if validation_error_message:
            conversation.append(
                HumanMessagePromptTemplate.from_template(FAILOVER_PROMPT, template_format="mustache").format(
                    validation_error_message=validation_error_message
                )
            )

        return conversation


class SchemaGeneratorToolsNode(AssistantNode):
    """
    Used for failover from generation errors.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        intermediate_steps = state.intermediate_steps or []
        if not intermediate_steps:
            return PartialAssistantState()

        action, _ = intermediate_steps[-1]
        prompt = (
            ChatPromptTemplate.from_template(FAILOVER_OUTPUT_PROMPT, template_format="mustache")
            .format_messages(output=action.tool_input, exception_message=action.log)[0]
            .content
        )

        return PartialAssistantState(
            intermediate_steps=[
                *intermediate_steps[:-1],
                (action, str(prompt)),
            ]
        )
