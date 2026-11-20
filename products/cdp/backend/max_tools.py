import re
import json
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from rest_framework import serializers

from posthog.hogql import errors as hogql_errors

from products.cdp.backend.prompts import (
    DESTINATION_LIMITATIONS_MESSAGE,
    HOG_EXAMPLE_MESSAGE,
    HOG_FUNCTION_FILTERS_ASSISTANT_ROOT_SYSTEM_PROMPT,
    HOG_FUNCTION_INPUTS_ASSISTANT_ROOT_SYSTEM_PROMPT,
    HOG_FUNCTION_INPUTS_SYSTEM_PROMPT,
    HOG_GRAMMAR_MESSAGE,
    HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT,
    IDENTITY_MESSAGE_HOG,
    INPUT_SCHEMA_TYPES_MESSAGE,
    TRANSFORMATION_LIMITATIONS_MESSAGE,
    TRANSFORMATION_STRUCTURE_MESSAGE,
    render_filters_system_prompt,
)
from products.cdp.backend.validation import compile_hog

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
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
    description: str = "Write or edit the Hog code for the data pipeline transformation function currently open in the editor, and apply the result to the editor"
    args_schema: type[BaseModel] = CreateHogTransformationFunctionArgs
    context_prompt_template: str = (
        HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT
        + "\n\n"
        + TRANSFORMATION_STRUCTURE_MESSAGE
        + "\n\n"
        + TRANSFORMATION_LIMITATIONS_MESSAGE
        + "\n\n"
        + DESTINATION_LIMITATIONS_MESSAGE
    )

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        current_hog_code = self.context.get("current_hog_code", "")

        system_content = (
            IDENTITY_MESSAGE_HOG
            + "\n\n<transformation_structure>\n"
            + TRANSFORMATION_STRUCTURE_MESSAGE
            + "\n</transformation_structure>\n\n"
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

        final_error: Optional[BaseException] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                assert isinstance(result.content, str)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                # Add error feedback to system message for retry
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            assert final_error is not None
            raise final_error

        return "```hog\n" + parsed_result.hog_code + "\n```", parsed_result.hog_code

    @property
    def _model(self) -> BaseChatModel:
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
        except serializers.ValidationError as e:
            raise PydanticOutputParserException(
                llm_output=hog_code,
                validation_message=f"The Hog code failed to compile: {_compile_error_message(e)}",
            )

        return HogTransformationOutput(hog_code=hog_code)


def _compile_error_message(error: serializers.ValidationError) -> str:
    # compile_hog replaces a parser or compiler error with a generic message, but the original error
    # stays on the exception chain. The retry prompt needs that original text, or the model repeats its mistake.
    if isinstance(error.__context__, hogql_errors.ExposedHogQLError):
        return str(error.__context__)
    errors = serializers.as_serializer_error(error)
    return " ".join(str(message) for messages in errors.values() for message in messages)


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

        system_content = render_filters_system_prompt(function_type, current_filters)

        user_content = f"Create filters for this hog function: {instructions}"

        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[BaseException] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                assert isinstance(result.content, str)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                # Add error feedback to system message for retry
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            assert final_error is not None
            raise final_error

        return (
            f"```json\n{json.dumps(parsed_result.filters, indent=2)}\n```",
            json.dumps(parsed_result.filters),
        )

    @property
    def _model(self) -> BaseChatModel:
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
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
    input_values: dict = Field(default_factory=dict, description="Changed input values, keyed by input key")


# The value types the model may change, with the Python types the input's editor can render.
# Other types hold IDs or structures the model cannot know, such as integration accounts and email
# senders, and a changed integration ID would leave its integration_field inputs on the old account.
EDITABLE_INPUT_VALUE_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "boolean": (bool, str),
    "dictionary": (dict,),
    "choice": (str,),
    "json": (dict, list, str, int, float, bool),
}


def _editable_input_schemas(inputs_schema: list) -> dict[str, dict]:
    return {
        schema["key"]: schema
        for schema in inputs_schema
        if isinstance(schema, dict)
        and "key" in schema
        and not schema.get("secret")
        and schema.get("type") in EDITABLE_INPUT_VALUE_TYPES
    }


def _input_values_for_prompt(current_inputs: dict, inputs_schema: list) -> dict:
    editable_schemas = _editable_input_schemas(inputs_schema)
    return {
        key: entry.get("value")
        for key, entry in current_inputs.items()
        if key in editable_schemas and isinstance(entry, dict) and not entry.get("secret")
    }


def _changed_input_values(proposed_values: dict, current_inputs_schema: list, new_inputs_schema: list) -> dict:
    # A suggestion can also retype an input, so a key the current schema locks stays locked
    # even when the suggested schema would make it editable.
    current_keys = {schema.get("key") for schema in current_inputs_schema if isinstance(schema, dict)}
    locked_keys = current_keys - _editable_input_schemas(current_inputs_schema).keys()
    editable_schemas = _editable_input_schemas(new_inputs_schema)
    return {
        key: value
        for key, value in proposed_values.items()
        if key in editable_schemas and key not in locked_keys and _fits_input(value, editable_schemas[key])
    }


def _fits_input(value: object, schema: dict) -> bool:
    if value is None:
        return not schema.get("required")
    return isinstance(value, EDITABLE_INPUT_VALUE_TYPES[schema["type"]])


class CreateHogFunctionInputsTool(MaxTool):
    name: str = "create_hog_function_inputs"
    description: str = "Generate or modify input variables for hog functions, and change their configured values, based on the current code and requirements"
    args_schema: type[BaseModel] = CreateHogFunctionInputsArgs
    context_prompt_template: str = HOG_FUNCTION_INPUTS_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self, instructions: str) -> tuple[str, list | dict]:
        current_inputs_schema = self.context.get("current_inputs_schema", [])
        hog_code = self.context.get("hog_code", "")
        current_input_values = _input_values_for_prompt(self.context.get("current_inputs") or {}, current_inputs_schema)

        system_content = (
            HOG_FUNCTION_INPUTS_SYSTEM_PROMPT
            + f"\n\nCurrent hog code:\n{hog_code}"
            + f"\nCurrent inputs schema:\n{current_inputs_schema}"
            + f"\nCurrent input values:\n{json.dumps(current_input_values)}"
            + "\n\n<input_schema_types>\n"
            + INPUT_SCHEMA_TYPES_MESSAGE
            + "\n</input_schema_types>"
        )

        user_content = f"Create or modify the input variables or their values for this function: {instructions}"

        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[BaseException] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                assert isinstance(result.content, str)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            assert final_error is not None
            raise final_error

        # A browser tab that loaded the editor before this tool could change values sends no
        # current_inputs. Its callback reads the artifact as the bare schema list and cannot apply values.
        editor_applies_values = "current_inputs" in self.context
        changed_values = (
            _changed_input_values(parsed_result.input_values, current_inputs_schema, parsed_result.inputs_schema)
            if editor_applies_values
            else {}
        )
        content = f"```json\n{json.dumps(parsed_result.inputs_schema, indent=2)}\n```"
        if changed_values:
            content += f"\n\nChanged values:\n```json\n{json.dumps(changed_values, indent=2)}\n```"

        if not editor_applies_values:
            return content, parsed_result.inputs_schema
        return content, {"inputs_schema": parsed_result.inputs_schema, "inputs": changed_values}

    @property
    def _model(self) -> BaseChatModel:
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
        )

    def _parse_output(self, output: str) -> HogFunctionInputsOutput:
        input_values = self._parse_input_values(output)
        output_without_values = re.sub(r"<input_values>.*?</input_values>", "", output, flags=re.DOTALL)

        match = re.search(r"<inputs_schema>(.*?)</inputs_schema>", output_without_values, re.DOTALL)
        if not match:
            # Try to find JSON array in the output
            json_match = re.search(r"\[[\s\S]*\]", output_without_values)
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

        return HogFunctionInputsOutput(inputs_schema=inputs_schema, input_values=input_values)

    def _parse_input_values(self, output: str) -> dict:
        match = re.search(r"<input_values>(.*?)</input_values>", output, re.DOTALL)
        if not match:
            return {}
        try:
            input_values = json.loads(match.group(1).strip())
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=output, validation_message=f"Invalid JSON in input values: {str(e)}"
            )
        if not isinstance(input_values, dict):
            raise PydanticOutputParserException(
                llm_output=output, validation_message="Input values must be a JSON object keyed by input key."
            )
        return input_values
