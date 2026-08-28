import { mkdirSync } from "node:fs";
import path from "node:path";
import { MACHINE_CLAUDE_CONFIG_DIR_ENV } from "@posthog/agent/adapters/claude/machine-config-dir";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `[env] Missing required environment variable: ${name}. bootstrap.ts must set this before any service/util is loaded.`,
    );
  }
  return value;
}

/**
 * Whether this is a development build (running via electron-vite dev).
 * Use this for dev/prod feature gates. Use `isPackaged` from @posthog/platform/app-meta
 * via DI only when you need ASAR-related behavior (e.g. .unpacked paths).
 */
export function isDevBuild(): boolean {
  return requireEnv("POSTHOG_CODE_IS_DEV") === "true";
}

export function getUserDataDir(): string {
  return requireEnv("POSTHOG_CODE_DATA_DIR");
}

export function getAppVersion(): string {
  return requireEnv("POSTHOG_CODE_VERSION");
}

export function ensureClaudeConfigDir(): void {
  const existing = process.env.CLAUDE_CONFIG_DIR;
  if (existing) {
    process.env[MACHINE_CLAUDE_CONFIG_DIR_ENV] = existing;
    return;
  }

  const claudeDir = path.join(getUserDataDir(), "claude");

  mkdirSync(claudeDir, { recursive: true });
  process.env.CLAUDE_CONFIG_DIR = claudeDir;
}
