from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.graph.agent_modes.factory import AgentDefinition
from ee.hogai.graph.agent_modes.nodes import AgentToolkit
from ee.hogai.tools import ExecuteSQLTool

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class SQLAgentToolkit(AgentToolkit):
    @property
    def default_tools(self) -> list[type["MaxTool"]]:
        return [
            *super().default_tools,
            ExecuteSQLTool,
        ]


sql_agent = AgentDefinition(
    mode=AgentMode.SQL,
    mode_description="Specialized mode capable of generating and executing SQL queries.",
    toolkit_class=SQLAgentToolkit,
)
