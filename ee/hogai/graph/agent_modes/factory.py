from dataclasses import dataclass, field

from pydantic import BaseModel

from posthog.schema import AgentMode

from .nodes import AgentExecutable, AgentToolkit, AgentToolsExecutable


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
class AgentModeDefinition:
    mode: AgentMode
    """The name of the agent's mode."""
    mode_description: str
    """The description of the agent's mode that will be injected into the tool. Keep it short and concise."""
    toolkit_class: type[AgentToolkit] = AgentToolkit
    """A custom toolkit class to use for the agent."""
    node_class: type[AgentExecutable] = AgentExecutable
    """A custom node class to use for the agent."""
    tools_node_class: type[AgentToolsExecutable] = AgentToolsExecutable
    """A custom tools node class to use for the agent."""
    positive_todo_examples: list[AgentExample] = field(default_factory=list)
    """Positive examples that will be injected into the `todo_write` tool. Use this field to explain the agent how it should orchestrate complex tasks using provided tools."""
    negative_todo_examples: list[AgentExample] = field(default_factory=list)
    """Negative examples that will be injected into the `todo_write` tool. Use this field to explain the agent how it should **NOT** orchestrate tasks using provided tools."""
