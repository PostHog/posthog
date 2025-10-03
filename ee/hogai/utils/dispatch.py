from collections.abc import Callable

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from ee.hogai.utils.types.actions import AssistantAction, DispatchedAction


def internal_dispatch(writer: StreamWriter, config: RunnableConfig | None) -> Callable[[AssistantAction], None]:
    if not config:
        raise AttributeError("Config is required to dispatch actions")

    def dispatch(action: AssistantAction) -> None:
        writer(DispatchedAction(langgraph_node=config.get("langgraph_node"), action=action))

    return dispatch
