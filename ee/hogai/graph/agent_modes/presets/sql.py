from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.tools import ExecuteSQLTool

from ..factory import AgentModeDefinition
from ..nodes import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class SQLAgentToolkit(AgentToolkit):
    @property
    def default_tools(self) -> list[type["MaxTool"]]:
        return [
            *super().default_tools,
            ExecuteSQLTool,
        ]


sql_agent = AgentModeDefinition(
    mode=AgentMode.SQL,
    mode_description="Specialized mode capable of generating and executing SQL queries.",
    toolkit_class=SQLAgentToolkit,
)
