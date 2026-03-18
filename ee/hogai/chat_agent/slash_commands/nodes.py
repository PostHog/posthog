from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from posthog.schema import HumanMessage

from ee.hogai.chat_agent.memory.nodes import MemoryOnboardingNode
from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.chat_agent.slash_commands.commands.feedback import FeedbackCommand
from ee.hogai.chat_agent.slash_commands.commands.remember import RememberCommand
from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.chat_agent.slash_commands.commands.usage import UsageCommand
from ee.hogai.core.agent_modes.const import SlashCommandName
from ee.hogai.core.node import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName


class SlashCommandHandlerNode(AssistantNode):
    """
    Generic handler that detects slash commands and executes the appropriate handler.

    This node detects slash commands and executes them directly, returning to END.
    For non-command messages, it routes to the normal conversation flow.
    """

    # Registry mapping slash commands to their handler classes.
    # Commands are matched by prefix, so /remember can take arguments.
    COMMAND_HANDLERS: dict[str, type[SlashCommand]] = {
        SlashCommandName.FIELD_USAGE: UsageCommand,
        SlashCommandName.FIELD_REMEMBER: RememberCommand,
        SlashCommandName.FIELD_FEEDBACK: FeedbackCommand,
        SlashCommandName.FIELD_TICKET: TicketCommand,
    }

    def _get_command(self, state: AssistantState) -> str | None:
        """Extract the slash command from the last human message, if any."""
        for msg in reversed(state.messages):
            if isinstance(msg, HumanMessage):
                content = msg.content.strip()
                # Check for exact match first, then prefix match (for commands with args)
                for command in self.COMMAND_HANDLERS:
                    if content == command or content.startswith(command + " "):
                        return command
                return None
        return None

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        command = self._get_command(state)
        if command is None:
            return None

        command_class = self.COMMAND_HANDLERS[command]
        command_instance = command_class(self._team, self._user)
        return await command_instance.execute(config, state)

    async def arouter(self, state: AssistantState) -> AssistantNodeName | list[Send]:
        """
        Route based on whether a slash command was detected.

        Returns:
            - END if a slash command was handled in arun
            - A list of Send objects for normal conversation flow (ROOT + MEMORY_COLLECTOR)
            - MEMORY_ONBOARDING if this is the first message and onboarding should run
        """
        command = self._get_command(state)
        if command is not None:
            return AssistantNodeName.END

        # No command detected - route to normal conversation flow
        send_list: list[Send] = [
            Send(AssistantNodeName.ROOT, state),
            Send(AssistantNodeName.MEMORY_COLLECTOR, state),
        ]

        # Check if memory onboarding should run instead
        memory_onboarding_should_run = await MemoryOnboardingNode(
            self._team, self._user
        ).should_run_onboarding_at_start(state)
        if memory_onboarding_should_run == "memory_onboarding":
            send_list = [Send(AssistantNodeName.MEMORY_ONBOARDING, state)]

        return send_list
