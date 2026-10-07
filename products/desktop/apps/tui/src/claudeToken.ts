import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

// The token `claude setup-token` prints, kept in a file only this user can read.
export const CLAUDE_TOKEN_PATH = join(
  homedir(),
  ".config",
  "posthog-tui",
  "claude-token",
);

export function isValidClaudeSetupToken(value: string): boolean {
  const token = value.trim();
  return /^sk-ant-oat01-\S{29,}$/.test(token) && token.length <= 4096;
}

export function loadClaudeToken(
  path: string = CLAUDE_TOKEN_PATH,
): string | null {
  try {
    const token = readFileSync(path, "utf8").trim();
    return token || null;
  } catch {
    return null;
  }
}

export function saveClaudeToken(
  token: string,
  path: string = CLAUDE_TOKEN_PATH,
): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  writeFileSync(path, `${token.trim()}\n`, { mode: 0o600 });
}

export function clearClaudeToken(path: string = CLAUDE_TOKEN_PATH): void {
  rmSync(path, { force: true });
}
