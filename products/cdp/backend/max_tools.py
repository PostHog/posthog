from typing import Optional
from common.hogvm.python.execute import validate_bytecode
from ee.hogai.tool import MaxTool
from posthog.cdp.validation import compile_hog
from posthog.hogql.ai import HOG_EXAMPLE_MESSAGE, HOG_GRAMMAR_MESSAGE, IDENTITY_MESSAGE_HOG
from products.cdp.backend.prompts import HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output


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
