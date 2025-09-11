from enum import Enum

from pydantic import BaseModel


class ResultEnum(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ResponseData(BaseModel):
    output: str


class AiRegexSchema(BaseModel):
    result: ResultEnum
    data: ResponseData

    class Config:
        extra = "forbid"  # This is equivalent to additionalProperties: False


# If you still need the original dictionary format for some reason, you can create it from the model
# AI_REGEX_SCHEMA = AiRegexSchema.model_json_schema()
