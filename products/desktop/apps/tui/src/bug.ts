import { homedir } from "node:os";
import { join } from "node:path";

export interface BugChat {
  id: string;
  title?: string;
  local: boolean;
}

// The first message of the local chat /bug starts: the report, and where to read the chat it came from.
export function bugMessage(report: string, chat: BugChat | null): string {
  const lines = [`Bug report: ${report}`];
  if (!chat) return lines.join("\n");
  lines.push(
    "",
    "It happened in this chat, so read its log to see what went on:",
  );
  lines.push(`- Task id: ${chat.id}`);
  if (chat.title) lines.push(`- Title: ${chat.title}`);
  lines.push(
    chat.local
      ? `- Runs on this machine; its log files are ${join(homedir(), ".config", "posthog-tui", "local", chat.id)}.*`
      : "- Runs in the cloud; read its run log with the PostHog task tools",
  );
  return lines.join("\n");
}
