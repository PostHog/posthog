from typing import Optional
import re
from ee.hogai.tool import MaxTool
from posthog.cdp.validation import compile_hog
from posthog.hogql.ai import HOG_EXAMPLE_MESSAGE, HOG_GRAMMAR_MESSAGE, IDENTITY_MESSAGE_HOG
from products.cdp.backend.prompts import HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException


class CreateHogTransformationFunctionArgs(BaseModel):
    instructions: str = Field(description="The instructions for what transformation to create.")


class HogTransformationOutput(BaseModel):
    hog_code: str


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
        return ChatOpenAI(model="gpt-4.1", temperature=0, disable_streaming=True)

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
