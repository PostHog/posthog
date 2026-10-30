// What pi's bash RPC returns for a command the user ran.
export interface ShellResult {
  output: string;
  exitCode: number | undefined;
  cancelled: boolean;
}

// The command in a composer message that starts with !, or null for any other message.
export function parseShell(text: string): string | null {
  const trimmed = text.trim();
  if (!trimmed.startsWith("!")) return null;
  const command = trimmed.slice(1).trim();
  return command || null;
}

// Why a ! command cannot run in this chat, or null when it can. A blocked command stays in the composer with the reason.
export function shellBlocked(chat: {
  taskId: string | null;
  isLocal: boolean;
  run: { status: string } | undefined;
  canControl: boolean;
}): string | null {
  if (!chat.taskId) return "Start a chat first, then run commands with !";
  if (chat.isLocal) return null;
  if (!chat.run || !chat.canControl)
    return "This chat has no run to run commands in yet";
  if (chat.run.status !== "queued" && chat.run.status !== "in_progress")
    return "This run has ended. Send a message to start it again, then run commands.";
  return null;
}
