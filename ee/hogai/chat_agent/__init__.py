from typing import TYPE_CHECKING, Any

__all__ = ["AssistantGraph"]


def __getattr__(name: str) -> Any:
    # Lazy (PEP 562): importing any chat_agent submodule used to eagerly pull `.graph` and its
    # whole mode_manager -> toolkit -> tools -> runner chain, which imports back here for
    # AssistantGraph — a cycle that only held together via the temporal.ai startup preload.
    if name == "AssistantGraph":
        from .graph import AssistantGraph

        return AssistantGraph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from .graph import AssistantGraph as AssistantGraph
