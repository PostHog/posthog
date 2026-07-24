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
  return /(^|\n)#{1,6}\s+\S/.test(trimmed);
}

export function getLatestAssistantText(
  notifications: SessionNotification[],
): string | null {
  const chunks: string[] = [];
  let started = false;

  for (let i = notifications.length - 1; i >= 0; i -= 1) {
    const update = notifications[i]?.update;
    if (!update) continue;

    if (update.sessionUpdate === "agent_message_chunk") {
      started = true;
      const content = update.content as {
        type?: string;
        text?: string;
      } | null;
      if (content?.type === "text" && content.text) {
        chunks.push(content.text);
      }
      continue;
    }

    if (started) {
      break;
    }
  }

  if (chunks.length === 0) return null;
  return chunks.reverse().join("");
}
