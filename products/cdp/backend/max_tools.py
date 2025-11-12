import re
import json
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from posthog.hogql.ai import (
    DESTINATION_LIMITATIONS_MESSAGE,
    EVENT_PROPERTY_TAXONOMY_MESSAGE,
    EVENT_TAXONOMY_MESSAGE,
    FILTER_TAXONOMY_MESSAGE,
    HOG_EXAMPLE_MESSAGE,
    HOG_FUNCTION_FILTERS_SYSTEM_PROMPT,
    HOG_FUNCTION_INPUTS_SYSTEM_PROMPT,
    HOG_GRAMMAR_MESSAGE,
    IDENTITY_MESSAGE_HOG,
    INPUT_SCHEMA_TYPES_MESSAGE,
    PERSON_TAXONOMY_MESSAGE,
    TRANSFORMATION_LIMITATIONS_MESSAGE,
)

from posthog.cdp.validation import compile_hog

from products.cdp.backend.prompts import (
    HOG_FUNCTION_FILTERS_ASSISTANT_ROOT_SYSTEM_PROMPT,
    HOG_FUNCTION_INPUTS_ASSISTANT_ROOT_SYSTEM_PROMPT,
    HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT,
)

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool


class CreateHogTransformationFunctionArgs(BaseModel):
    instructions: str = Field(description="The instructions for what transformation to create.")


class HogTransformationOutput(BaseModel):
    hog_code: str


class CreateHogFunctionFiltersArgs(BaseModel):
    instructions: str = Field(description="The instructions for what filters to create.")


class HogFunctionFiltersOutput(BaseModel):
    filters: dict


class CreateHogTransformationFunctionTool(MaxTool):
    name: str = "create_hog_transformation_function"  # Must match a value in AssistantTool enum
    description: str = "Write or edit the hog code to create your desired function and apply it to the current editor"
    args_schema: type[BaseModel] = CreateHogTransformationFunctionArgs
    context_prompt_template: str = (
        HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT
        + "\n\n"
        + TRANSFORMATION_LIMITATIONS_MESSAGE
        + "\n\n"
        + DESTINATION_LIMITATIONS_MESSAGE
    )

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
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
            inject_context=False,
        )

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
    name: str = "create_hog_function_filters"  # Must match a value in AssistantTool enum
    description: str = (
        "Create or edit filters for hog functions to specify which events and properties trigger the function"
    )
    args_schema: type[BaseModel] = CreateHogFunctionFiltersArgs
    context_prompt_template: str = HOG_FUNCTION_FILTERS_ASSISTANT_ROOT_SYSTEM_PROMPT

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
        return MaxChatOpenAI(
            model="gpt-4.1", temperature=0.3, disable_streaming=True, user=self._user, team=self._team, billable=True
        )

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


class CreateHogFunctionInputsArgs(BaseModel):
    instructions: str = Field(description="The instructions for what inputs to generate or modify.")


class HogFunctionInputsOutput(BaseModel):
    inputs_schema: list = Field(description="The generated inputs schema for the hog function")


class CreateHogFunctionInputsTool(MaxTool):
    name: str = "create_hog_function_inputs"
    description: str = "Generate or modify input variables for hog functions based on the current code and requirements"
    args_schema: type[BaseModel] = CreateHogFunctionInputsArgs
    context_prompt_template: str = HOG_FUNCTION_INPUTS_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self, instructions: str) -> tuple[str, list]:
        current_inputs_schema = self.context.get("current_inputs_schema", [])
        hog_code = self.context.get("hog_code", "")

        system_content = (
            HOG_FUNCTION_INPUTS_SYSTEM_PROMPT
            + f"\n\nCurrent hog code:\n{hog_code}"
            + f"\nCurrent inputs schema:\n{current_inputs_schema}"
            + "\n\n<input_schema_types>\n"
            + INPUT_SCHEMA_TYPES_MESSAGE
            + "\n</input_schema_types>"
        )

        user_content = f"Create or modify the input variables for this function: {instructions}"

        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            raise final_error

        # Format the output for display
        import json

        formatted_json = json.dumps(parsed_result.inputs_schema, indent=2)
        return f"```json\n{formatted_json}\n```", parsed_result.inputs_schema

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-4.1", temperature=0.3, disable_streaming=True, user=self._user, team=self._team, billable=True
        )

    def _parse_output(self, output: str) -> HogFunctionInputsOutput:
        import json

        match = re.search(r"<inputs_schema>(.*?)</inputs_schema>", output, re.DOTALL)
        if not match:
            # Try to find JSON array in the output
            json_match = re.search(r"\[[\s\S]*\]", output)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise PydanticOutputParserException(
                    llm_output=output, validation_message="Could not find inputs_schema in the response."
                )
        else:
            json_str = match.group(1).strip()

        try:
            inputs_schema = json.loads(json_str)
            if not isinstance(inputs_schema, list):
                raise PydanticOutputParserException(
                    llm_output=output, validation_message="Inputs schema must be a list."
                )
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=output, validation_message=f"Invalid JSON in inputs schema: {str(e)}"
            )

        return HogFunctionInputsOutput(inputs_schema=inputs_schema)
