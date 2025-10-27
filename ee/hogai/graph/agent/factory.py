from dataclasses import dataclass

from ee.hogai.graph.agent.nodes import AgentNode, AgentToolkit, AgentToolsNode
from ee.hogai.utils.types.base import AgentMode


@dataclass
class AgentDefinition:
    mode: AgentMode
    """The name of the agent's mode."""
    mode_description: str
    """The description of the agent's mode that will be injected into the tool. Keep it short and concise."""
    toolkit_class: type[AgentToolkit] = AgentToolkit
    """A custom toolkit class to use for the agent."""
    node_class: type[AgentNode] = AgentNode
    """A custom node class to use for the agent."""
    tools_node_class: type[AgentToolsNode] = AgentToolsNode
    """A custom tools node class to use for the agent."""
