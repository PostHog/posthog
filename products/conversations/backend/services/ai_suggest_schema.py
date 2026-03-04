from enum import Enum

from pydantic import BaseModel


class ConversationTypeEnum(str, Enum):
    issue = "issue"
    question = "question"


class RefinedQuerySchema(BaseModel):
    is_safe: bool
    decline_reason: str | None = None
    conversation_type: ConversationTypeEnum
    refined_query: str
    intent_summary: str

    class Config:
        extra = "forbid"


class SuggestedReplySchema(BaseModel):
    reply_text: str

    class Config:
        extra = "forbid"


class ResponseValidationSchema(BaseModel):
    is_valid: bool
    issues: list[str] = []

    class Config:
        extra = "forbid"
