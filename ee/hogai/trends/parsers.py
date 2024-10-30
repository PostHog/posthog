import json

from pydantic import ValidationError

from ee.hogai.trends.utils import GenerateTrendOutputModel


class PydanticOutputParserException(ValueError):
    llm_output: str
    """Serialized LLM output."""
    validation_message: str
    """Pydantic validation error message."""

    def __init__(self, llm_output: str, validation_message: str):
        super().__init__(llm_output)
        self.llm_output = llm_output
        self.validation_message = validation_message


def parse_generated_trends_output(output: dict) -> GenerateTrendOutputModel:
    try:
        return GenerateTrendOutputModel.model_validate(output)
    except ValidationError as e:
        raise PydanticOutputParserException(llm_output=json.dumps(output), validation_message=e.json(include_url=False))
