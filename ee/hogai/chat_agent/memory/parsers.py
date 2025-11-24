from typing import Any

from langchain_core.messages import AIMessage


def compressed_memory_parser(memory: str) -> str:
    """
    Remove newlines between paragraphs.
    """
    return memory.replace("\n\n", "\n")


class MemoryCollectionCompleted(Exception):
    """
    Raised when the agent finishes collecting memory.
    """

    pass


def raise_memory_updated(response: Any):
    if isinstance(response, AIMessage) and ("[Done]" in response.content or not response.tool_calls):
        raise MemoryCollectionCompleted
    return response
