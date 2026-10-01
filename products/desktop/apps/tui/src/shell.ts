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
