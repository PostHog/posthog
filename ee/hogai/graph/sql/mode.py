from posthog.schema import AgentMode

from ee.hogai.graph.agent.factory import AgentDefinition
from ee.hogai.graph.agent.nodes import AgentNode


class SQLAgentNode(AgentNode):
    pass


sql_agent = AgentDefinition(AgentMode.SQL, "SQL Agent")
