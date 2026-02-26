from enum import Enum

from pydantic import BaseModel


class ConversationTypeEnum(str, Enum):
    issue = "issue"
    question = "question"


class ConversationClassificationSchema(BaseModel):
    conversation_type: ConversationTypeEnum

    class Config:
        extra = "forbid"


class SuggestedReplySchema(BaseModel):
    reply_text: str

    class Config:
        extra = "forbid"
