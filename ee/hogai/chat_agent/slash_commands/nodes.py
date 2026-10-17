from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantMessageMetadata, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.chat_agent.slash_commands.commands.feedback import FeedbackCommand
from ee.hogai.chat_agent.slash_commands.commands.remember import RememberCommand
from ee.hogai.chat_agent.slash_commands.commands.ticket import TicketCommand
from ee.hogai.chat_agent.slash_commands.commands.usage import UsageCommand
from ee.hogai.core.agent_modes.const import SlashCommandName
from ee.hogai.core.node import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantMessageUnion, AssistantNodeName


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
        result = await command_instance.execute(config, state)
        return self._stamp_message_source(result, command)

    @staticmethod
    def _stamp_message_source(result: PartialAssistantState, command: str) -> PartialAssistantState:
        if not result.messages:
            return result
        source = f"slash_command:{command.lstrip('/')}"
        stamped: list[AssistantMessageUnion] = []
        for msg in result.messages:
            if isinstance(msg, AssistantMessage) and (msg.meta is None or msg.meta.source is None):
                meta = (
                    msg.meta.model_copy(update={"source": source})
                    if msg.meta
                    else AssistantMessageMetadata(source=source)
                )
                stamped.append(msg.model_copy(update={"meta": meta}))
            else:
                stamped.append(msg)
        return result.model_copy(update={"messages": stamped})

    async def arouter(self, state: AssistantState) -> AssistantNodeName:
        """
        Route based on whether a slash command was detected.

        Returns:
            - END if a slash command was handled in arun
            - SCOPE_GATE for every other message, which then picks the normal conversation flow
        """
        if self._get_command(state) is not None:
            return AssistantNodeName.END
        return AssistantNodeName.SCOPE_GATE
