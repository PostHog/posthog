from typing import Optional, List
from common.hogvm.python.execute import validate_bytecode
from ee.hogai.tool import MaxTool
from posthog.cdp.validation import compile_hog
from posthog.hogql.ai import HOG_EXAMPLE_MESSAGE, HOG_GRAMMAR_MESSAGE, IDENTITY_MESSAGE_HOG
from products.cdp.backend.prompts import HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
import json


class HogFunctionInputSchema(BaseModel):
    type: str = Field(description="The type of input (string, boolean, dictionary, choice, json, integration, integration_field, email)")
    key: str = Field(description="The unique key for this input")
    label: str = Field(description="Human readable label for this input")
    required: bool = Field(description="Whether this input is required", default=False)
    default: Optional[str] = Field(description="Default value for this input", default=None)
    description: Optional[str] = Field(description="Description of what this input is used for", default=None)
    choices: Optional[List[dict]] = Field(description="List of choices for choice type inputs", default=None)
    secret: Optional[bool] = Field(description="Whether this input should be treated as secret", default=False)
    hidden: Optional[bool] = Field(description="Whether this input should be hidden in the UI", default=False)
    integration: Optional[str] = Field(description="Integration type for integration inputs", default=None)
    integration_key: Optional[str] = Field(description="Integration key for integration inputs", default=None)
    integration_field: Optional[str] = Field(description="Integration field for integration inputs", default=None)
    requires_field: Optional[str] = Field(description="Field that this input requires", default=None)
    requiredScopes: Optional[str] = Field(description="Required scopes for this input", default=None)
    templating: Optional[bool] = Field(description="Whether this input supports templating", default=False)

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        # Remove None values to match frontend expectations
        return {k: v for k, v in data.items() if v is not None}


class CreateHogFunctionInputsArgs(BaseModel):
    instructions: str = Field(description="The instructions for what inputs to create or modify.")


class HogFunctionInputsOutput(BaseModel):
    inputs_schema: List[HogFunctionInputSchema]


class CreateHogFunctionInputsTool(MaxTool):
    name: str = "create_hog_function_inputs"
    description: str = "Create or modify the input schema for a Hog function"
    thinking_message: str = "Designing your function inputs"
    args_schema: type[BaseModel] = CreateHogFunctionInputsArgs
    root_system_prompt_template: str = """
The user is currently configuring inputs for a Hog function. They expect your help with designing and modifying input schemas.

When given a request to create or modify inputs:
1. Always return a complete input schema object
2. Use the most appropriate type for each input:
   - string: For text input
   - boolean: For true/false flags
   - json: For structured data like arrays or objects
   - choice: For selecting from predefined options
   - dictionary: For key-value pairs
   - integration: For external service connections
   - email: For email addresses
3. Include clear descriptions that explain the purpose and format
4. Set sensible default values when possible
5. Make inputs required only when they are truly necessary
6. Use snake_case for keys and clear, descriptive labels
7. Group related inputs logically

Examples of good input schemas:

Example 1 - Properties to Drop:
{
  "type": "json",
  "key": "properties_to_drop",
  "label": "Properties to Drop",
  "description": "List of property names to drop from the event",
  "required": false,
  "default": "[]"
}

Example 2 - PII Hashing Configuration:
[
  {
    "key": "properties_to_hash",
    "type": "string",
    "label": "Properties to Hash",
    "description": "Comma-separated list of property paths to hash (e.g. '$ip,$email,$set.$phone')",
    "default": "$ip",
    "secret": false,
    "required": true
  },
  {
    "key": "hash_distinct_id",
    "type": "boolean",
    "label": "Hash Distinct ID",
    "description": "Whether to hash the distinct_id field",
    "default": false,
    "secret": false,
    "required": false
  },
  {
    "key": "salt",
    "type": "string",
    "label": "Salt",
    "description": "Optional salt to add to the hashed values for additional security",
    "default": "",
    "secret": true,
    "required": false
  }
]

IMPORTANT: This is currently your primary task. Therefore `create_hog_function_inputs` is currently your primary tool.
Use `create_hog_function_inputs` when answering ANY requests remotely related to function inputs (including adding, modifying, or removing inputs).
It's very important to disregard other tools for these purposes - the user expects `create_hog_function_inputs`.

NOTE: When calling the `create_hog_function_inputs` tool, do not provide any response other than the tool call.

After the tool completes, do NOT repeat the schema, as the user can see it. Only summarize the changes, comprehensively, but in only one brief sentence."""

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """Design an input schema based on the current schema and user request.
                    
Here is an example of what the schema should look like:

[
  {
    "type": "json",
    "key": "properties_to_drop",
    "label": "Properties to Drop",
    "description": "List of property names to drop from the event",
    "required": false,
    "default": "[]"
  }
]

Guidelines:
- Always return a complete input schema object
- Use appropriate types (string, boolean, dictionary, choice, json, etc.)
- Include descriptions for clarity
- Set sensible defaults when possible
- Use snake_case for keys
- Make inputs required only when necessary

Current schema:
{{{current_inputs_schema}}}"""
                ),
                (
                    "user",
                    "Create or modify the input schema to satisfy this request: " + instructions,
                ),
            ],
            template_format="mustache",
        )

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                chain = prompt | self._model
                result = chain.invoke(self.context)
                parsed_result = self._parse_output(result)
                break
            except PydanticOutputParserException as e:
                prompt += f"Avoid this error: {str(e)}"
                final_error = e
        else:
            raise final_error

        # Convert Pydantic models to dictionaries for JSON serialization
        schema_dicts = [input_schema.model_dump() for input_schema in parsed_result.inputs_schema]
        formatted_json = json.dumps({"inputs_schema": schema_dicts}, indent=2)
        return "```json\n" + formatted_json + "\n```", json.dumps(schema_dicts)

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4", temperature=0, disable_streaming=True).with_structured_output(
            HogFunctionInputsOutput,
            method="function_calling",
            include_raw=False,
        )

    def _parse_output(self, output):  # type: ignore
        result = parse_pydantic_structured_output(HogFunctionInputsOutput)(output)
        assert result is not None

        # Validate the schema
        for input_schema in result.inputs_schema:
            if input_schema.type not in [
                "string", "boolean", "dictionary", "choice", "json", 
                "integration", "integration_field", "email"
            ]:
                raise PydanticOutputParserException(
                    llm_output=str(input_schema),
                    validation_message=f"Invalid input type: {input_schema.type}. Must be one of: string, boolean, dictionary, choice, json, integration, integration_field, email",
                )

        print(result)
        return result


class CreateHogTransformationFunctionArgs(BaseModel):
    instructions: str = Field(description="The instructions for what transformation to create.")


class HogTransformationOutput(BaseModel):
    hog_code: str


class CreateHogTransformationFunctionTool(MaxTool):
    name: str = "create_hog_transformation_function"  # Must match a value in AssistantContextualTool enum
    description: str = (
        "Write or edit the hog code to create your desired transformation and apply it to the current editor"
    )
    thinking_message: str = "Creating your desired transformation"
    args_schema: type[BaseModel] = CreateHogTransformationFunctionArgs
    root_system_prompt_template: str = HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    IDENTITY_MESSAGE_HOG
                    + "\n\n<example_hog_code>\n"
                    + HOG_EXAMPLE_MESSAGE
                    + "\n</example_hog_code>\n\n"
                    + "\n\n<hog_grammar>\n"
                    + HOG_GRAMMAR_MESSAGE
                    + "\n</hog_grammar>\n\n"
                    + "\n\n<current_hog_code>\n{{{current_hog_code}}}\n</current_hog_code>"
                    + "\n\nRemove all line breaks and carriage returns, and strip whitespace."
                    + "\n\nReturn the hog code nicely formatted.",
                ),
                (
                    "user",
                    "Write a Hog transformation or tweak the current one to satisfy this request: " + instructions,
                ),
            ],
            template_format="mustache",
        )

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                chain = prompt | self._model
                result = chain.invoke(self.context)
                parsed_result = self._parse_output(result)
                break
            except PydanticOutputParserException as e:
                prompt += f"Avoid this error: {str(e)}"
                final_error = e
        else:
            raise final_error

        return "```hog\n" + parsed_result.hog_code + "\n```", parsed_result.hog_code

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0, disable_streaming=True).with_structured_output(
            HogTransformationOutput,
            method="function_calling",
            include_raw=False,
        )

    def _parse_output(self, output):  # type: ignore
        result = parse_pydantic_structured_output(HogTransformationOutput)(output)
        assert result is not None

        # Validate that the Hog code compiles to bytecode
        try:
            compiled_result = compile_hog(result.hog_code, "transformation")
            if compiled_result:
                is_valid, error_message = validate_bytecode(compiled_result, {})
                if not is_valid:
                    raise PydanticOutputParserException(
                        llm_output=result.hog_code,
                        validation_message=f"The Hog bytecode validation failed: {error_message}",
                    )
        except Exception as e:
            raise PydanticOutputParserException(
                llm_output=result.hog_code, validation_message=f"The Hog code failed to compile: {str(e)}"
            )

        return result
