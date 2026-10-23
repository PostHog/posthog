import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export function pinnedSettingsDir(): string {
  return path.join(
    process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude"),
    "posthog-session-settings",
  );
}

export function isPinnedSettingsFile(value: string): boolean {
  return path.dirname(value) === pinnedSettingsDir();
}

/** Removes every pinned settings file; call only once no session is running. */
export async function cleanupAllPinnedSettings(): Promise<void> {
  const dir = pinnedSettingsDir();
  let entries: string[];
  try {
    entries = await fs.promises.readdir(dir);
  } catch {
    return;
  }
  await Promise.all(
    entries
      .filter((entry) => entry.endsWith(".json"))
      .map((entry) =>
        fs.promises.rm(path.join(dir, entry), { force: true }).catch(() => {}),
      ),
  );
}
