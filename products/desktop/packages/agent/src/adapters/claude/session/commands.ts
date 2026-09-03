import type { AvailableCommand } from "@agentclientprotocol/sdk";
import type { SlashCommand } from "@anthropic-ai/claude-agent-sdk";

const UNSUPPORTED_COMMANDS = [
  "context",
  "cost",
  "keybindings-help",
  "login",
  "logout",
  "output-style:new",
  "release-notes",
  "todos",
];

export function getAvailableSlashCommands(
  commands: SlashCommand[],
): AvailableCommand[] {
  const available = commands
    .map((command) => {
      const input =
        command.argumentHint != null
          ? {
              hint: Array.isArray(command.argumentHint)
                ? command.argumentHint.join(" ")
                : command.argumentHint,
            }
          : null;
      let name = command.name;
      if (command.name.endsWith(" (MCP)")) {
        name = `mcp:${name.replace(" (MCP)", "")}`;
      }
      return {
        name,
        description: command.description || "",
        input,
      };
    })
    .filter(
      (command: AvailableCommand) =>
        !UNSUPPORTED_COMMANDS.includes(command.name),
    );
  // /clear is implemented by the adapter (clearConversation), not forwarded
  // to the SDK — advertise it even when the SDK doesn't list it.
  if (!available.some((command) => command.name === "clear")) {
    available.push({
      name: "clear",
      description: "Clear conversation history and free up context",
      input: null,
    });
  }
  return available;
}
