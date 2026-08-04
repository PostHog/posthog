import * as os from "node:os";
import * as path from "node:path";
import type { SessionNotification } from "@agentclientprotocol/sdk";

function getClaudeConfigDir(): string {
  return process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
}

export function getClaudePlansDir(): string {
  return path.join(getClaudeConfigDir(), "plans");
}

export function isClaudePlanFilePath(filePath: string | undefined): boolean {
  if (!filePath) return false;
  const resolved = path.resolve(filePath);
  const plansDir = path.resolve(getClaudePlansDir());
  return resolved === plansDir || resolved.startsWith(plansDir + path.sep);
}

export function isPlanReady(plan: string | undefined): boolean {
  if (!plan) return false;
  const trimmed = plan.trim();
  if (trimmed.length < 40) return false;
  if (/(^|\n)#{1,6}\s+\S/.test(trimmed)) return true;
  // Models that emit plain-text plans (no markdown heading) still carry
  // real content. Accept longer multi-line text as a stand-in.
  const lineCount = trimmed.split(/\r?\n/).filter((line) => line.trim()).length;
  return lineCount >= 4;
}

// Original strict variant: only considers the last contiguous text run and
// returns null when anything else follows it (e.g. the ExitPlanMode call).
export function getLatestAssistantText(
  notifications: SessionNotification[],
): string | null {
  return collectTrailingText(notifications, false);
}

// Extended variant: skips past a trailing ExitPlanMode tool call (or thought
// chunks) so models that end their turn on the tool call still surface the
// last assistant text they wrote.
export function getLatestAssistantTextExtended(
  notifications: SessionNotification[],
): string | null {
  return collectTrailingText(notifications, true);
}

function collectTrailingText(
  notifications: SessionNotification[],
  extendPastToolCall: boolean,
): string | null {
  const chunks: string[] = [];
  const maxNotifications = 200;
  let scanned = 0;

  for (
    let i = notifications.length - 1;
    i >= 0 && scanned < maxNotifications;
    i -= 1
  ) {
    const update = notifications[i]?.update;
    if (!update) continue;
    scanned += 1;

    if (update.sessionUpdate === "agent_message_chunk") {
      const content = update.content as {
        type?: string;
        text?: string;
      } | null;
      if (content?.type === "text" && content.text) {
        chunks.push(content.text);
      }
      continue;
    }

    if (
      extendPastToolCall &&
      chunks.length === 0 &&
      update.sessionUpdate === "tool_call" &&
      isExitPlanModeCall(update)
    ) {
      continue;
    }

    if (
      extendPastToolCall &&
      chunks.length === 0 &&
      update.sessionUpdate === "agent_thought_chunk"
    ) {
      continue;
    }

    if (chunks.length > 0) {
      break;
    }
    if (!extendPastToolCall) {
      break;
    }
  }

  return chunks.length === 0 ? null : chunks.reverse().join("");
}

function isExitPlanModeCall(update: unknown): boolean {
  const candidate = update as {
    _meta?: { claudeCode?: { toolName?: string } };
    toolName?: string;
    name?: string;
  };
  return (
    (candidate._meta?.claudeCode?.toolName ??
      candidate.toolName ??
      candidate.name) === "ExitPlanMode"
  );
}
