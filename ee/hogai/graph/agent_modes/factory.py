from dataclasses import dataclass, field

from pydantic import BaseModel

from ee.hogai.graph.agent_modes.nodes import AgentNode, AgentToolkit, AgentToolsNode
from ee.hogai.utils.types.base import AgentMode


class AgentExample(BaseModel):
    """
    Custom agent example to correct the agent's behavior through few-shot prompting.
    The example will be formatted as follows:
    ```
    <example>
    {example}

    <reasoning>
    {reasoning}
    </reasoning>
    </example>
    ```
    """

    example: str
    reasoning: str | None = None


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
    positive_todo_examples: list[AgentExample] = field(default_factory=list)
    """Positive examples that will be injected into the `todo_write` tool. Use this field to explain the agent how it should orchestrate complex tasks using provided tools."""
    negative_todo_examples: list[AgentExample] = field(default_factory=list)
    """Negative examples that will be injected into the `todo_write` tool. Use this field to explain the agent how it should **NOT** orchestrate tasks using provided tools."""
