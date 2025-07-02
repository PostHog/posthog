from typing import Optional
import re
import json
from ee.hogai.tool import MaxTool
from posthog.cdp.validation import compile_hog
from posthog.hogql.ai import (
    HOG_EXAMPLE_MESSAGE,
    HOG_GRAMMAR_MESSAGE,
    IDENTITY_MESSAGE_HOG,
    HOG_FUNCTION_FILTERS_SYSTEM_PROMPT,
    EVENT_TAXONOMY_MESSAGE,
    EVENT_PROPERTY_TAXONOMY_MESSAGE,
    PERSON_TAXONOMY_MESSAGE,
    FILTER_TAXONOMY_MESSAGE,
)
from products.cdp.backend.prompts import (
    HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT,
    HOG_FUNCTION_FILTERS_ASSISTANT_ROOT_SYSTEM_PROMPT,
)
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException


class CreateHogTransformationFunctionArgs(BaseModel):
    instructions: str = Field(description="The instructions for what transformation to create.")


class HogTransformationOutput(BaseModel):
    hog_code: str


class CreateHogFunctionFiltersArgs(BaseModel):
    instructions: str = Field(description="The instructions for what filters to create.")


class HogFunctionFiltersOutput(BaseModel):
    filters: dict


class CreateHogTransformationFunctionTool(MaxTool):
    name: str = "create_hog_transformation_function"  # Must match a value in AssistantContextualTool enum
    description: str = "Write or edit the hog code to create your desired function and apply it to the current editor"
    thinking_message: str = "Creating your desired function"
    args_schema: type[BaseModel] = CreateHogTransformationFunctionArgs
    root_system_prompt_template: str = HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        current_hog_code = self.context.get("current_hog_code", "")

        system_content = (
            IDENTITY_MESSAGE_HOG
            + "\n\n<example_hog_code>\n"
            + HOG_EXAMPLE_MESSAGE
            + "\n</example_hog_code>\n\n"
            + "\n\n<hog_grammar>\n"
            + HOG_GRAMMAR_MESSAGE
            + "\n</hog_grammar>\n\n"
            + "\n\n<current_hog_code>\n"
            + current_hog_code
            + "\n</current_hog_code>"
            + "\n\nReturn ONLY the hog code inside <hog_code> tags. Do not add any other text or explanation."
        )

        user_content = "Write a Hog transformation or tweak the current one to satisfy this request: " + instructions

        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                # Add error feedback to system message for retry
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            raise final_error

        return "```hog\n" + parsed_result.hog_code + "\n```", parsed_result.hog_code

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1", temperature=0.3, disable_streaming=True)

    def _parse_output(self, output: str) -> HogTransformationOutput:
        match = re.search(r"<hog_code>(.*?)</hog_code>", output, re.DOTALL)
        if not match:
            # The model may have returned the code without tags, or with markdown
            hog_code = re.sub(
                r"^\s*```hog\s*\n(.*?)\n\s*```\s*$", r"\1", output, flags=re.DOTALL | re.MULTILINE
            ).strip()
        else:
            hog_code = match.group(1).strip()

        if not hog_code:
            raise PydanticOutputParserException(
                llm_output=output, validation_message="The model returned an empty hog code response."
            )

        try:
            compile_hog(hog_code, "transformation")
        except Exception as e:
            raise PydanticOutputParserException(
                llm_output=hog_code, validation_message=f"The Hog code failed to compile: {str(e)}"
            )

        return HogTransformationOutput(hog_code=hog_code)


class CreateHogFunctionFiltersTool(MaxTool):
    name: str = "create_hog_function_filters"  # Must match a value in AssistantContextualTool enum
    description: str = (
        "Create or edit filters for hog functions to specify which events and properties trigger the function"
    )
    thinking_message: str = "Setting up filters"
    args_schema: type[BaseModel] = CreateHogFunctionFiltersArgs
    root_system_prompt_template: str = HOG_FUNCTION_FILTERS_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        current_filters = self.context.get("current_filters", "{}")
        function_type = self.context.get("function_type", "destination")

        system_content = (
            HOG_FUNCTION_FILTERS_SYSTEM_PROMPT
            + f"\n\nCurrent filters: {current_filters}"
            + f"\nFunction type: {function_type}"
            + "\n\n<event_taxonomy>\n"
            + EVENT_TAXONOMY_MESSAGE
            + "\n</event_taxonomy>\n\n"
            + "\n\n<event_property_taxonomy>\n"
            + EVENT_PROPERTY_TAXONOMY_MESSAGE
            + "\n</event_property_taxonomy>\n\n"
            + "\n\n<person_property_taxonomy>\n"
            + PERSON_TAXONOMY_MESSAGE
            + "\n</person_property_taxonomy>\n\n"
            + "\n\n<filter_taxonomy>\n"
            + FILTER_TAXONOMY_MESSAGE
            + "\n</filter_taxonomy>"
        )

        user_content = f"Create filters for this hog function: {instructions}"

        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                # Add error feedback to system message for retry
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            raise final_error

        return f"```json\n{json.dumps(parsed_result.filters, indent=2)}\n```", json.dumps(parsed_result.filters)

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1", temperature=0.3, disable_streaming=True)

    def _parse_output(self, output: str) -> HogFunctionFiltersOutput:
        match = re.search(r"<filters>(.*?)</filters>", output, re.DOTALL)
        if not match:
            # The model may have returned the JSON without tags, or with markdown
            json_str = re.sub(
                r"^\s*```json\s*\n(.*?)\n\s*```\s*$", r"\1", output, flags=re.DOTALL | re.MULTILINE
            ).strip()
        else:
            json_str = match.group(1).strip()

        if not json_str:
            raise PydanticOutputParserException(
                llm_output=output, validation_message="The model returned an empty filters response."
            )

        try:
            filters = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=json_str, validation_message=f"The filters JSON failed to parse: {str(e)}"
            )

        return HogFunctionFiltersOutput(filters=filters)
