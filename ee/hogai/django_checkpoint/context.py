"""
Checkpoint context for the Django checkpoint system.

This is in a separate file to avoid circular imports.
"""

from typing import Optional
from pydantic import BaseModel, Field

from ee.hogai.utils.types import GraphContext, GraphType
from ee.models.assistant import Conversation


class CheckpointContext(BaseModel):
    graph_type: GraphType
    graph_context: GraphContext
    thread_id: Optional[str] = Field(default=None)
    thread_type: Optional[Conversation.Type] = Field(default=None)
