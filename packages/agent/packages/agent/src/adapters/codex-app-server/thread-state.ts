import { readdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

/**
 * Whether codex still holds the persisted rollout for `threadId` — written as
 * `CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<threadId>.jsonl` — i.e.
 * whether `thread/resume` can restore the thread natively. Mirrors codex's own
 * CODEX_HOME resolution (env override, else ~/.codex).
 */
export async function hasCodexThreadState(threadId: string): Promise<boolean> {
  if (!threadId) return false;
  const codexHome = process.env.CODEX_HOME || path.join(os.homedir(), ".codex");
  const sessionsDir = path.join(codexHome, "sessions");
  const suffix = `-${threadId}.jsonl`;
  try {
    const entries = await readdir(sessionsDir, { recursive: true });
    return entries.some((entry) => {
      const name = path.basename(entry);
      return name.startsWith("rollout-") && name.endsWith(suffix);
    });
  } catch {
    return false;
  }
}
