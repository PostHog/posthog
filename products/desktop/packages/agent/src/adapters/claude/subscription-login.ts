import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import type { Logger } from "../../utils/logger";

const STATUS_TIMEOUT_MS = 15_000;

export interface ClaudeLoginCheckOptions {
  /** Bundled Claude CLI path — must be the same binary sessions spawn. */
  claudeCliPath: string;
  logger?: Logger;
  timeoutMs?: number;
}

/**
 * Whether this machine has a Claude Code login the CLI can use.
 *
 * Read-only by design: we never read, copy, or refresh provider credentials.
 * The check spawns `claude auth status` and reads only the exit code, using
 * the same credential-stripped env a machine-auth session gets, so the answer
 * matches what a session would actually authenticate with. Login itself is
 * managed by the CLI (`claude` → `/login`); there is no in-app login flow.
 */
export async function hasClaudeLogin(
  options: ClaudeLoginCheckOptions,
): Promise<boolean> {
  if (!existsSync(options.claudeCliPath)) {
    options.logger?.debug("Claude CLI not found, reporting no login", {
      claudeCliPath: options.claudeCliPath,
    });
    return false;
  }

  // The legacy CLI ships as cli.js and needs a JS runtime to start.
  const isLegacyJs = options.claudeCliPath.endsWith(".js");
  const command = isLegacyJs ? process.execPath : options.claudeCliPath;
  const args = isLegacyJs
    ? [options.claudeCliPath, "auth", "status"]
    : ["auth", "status"];

  const env: NodeJS.ProcessEnv = { ...process.env };
  // Mirror the machine-auth session env: a stripped ambient credential must
  // not make the check report an auth source sessions would not use.
  delete env.ANTHROPIC_BASE_URL;
  delete env.ANTHROPIC_AUTH_TOKEN;
  delete env.ANTHROPIC_API_KEY;
  delete env.ANTHROPIC_CUSTOM_HEADERS;
  if (process.versions.electron || process.env.ELECTRON_RUN_AS_NODE) {
    env.ELECTRON_RUN_AS_NODE = "1";
  }

  return new Promise<boolean>((resolve) => {
    let settled = false;
    const finish = (loggedIn: boolean): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(loggedIn);
    };

    const child = spawn(command, args, {
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      finish(false);
    }, options.timeoutMs ?? STATUS_TIMEOUT_MS);

    // Output can contain account details; never logged, only counted.
    let outputLength = 0;
    child.stdout?.on("data", (chunk: Buffer) => {
      outputLength += chunk.length;
    });
    child.stderr?.on("data", () => {
      outputLength += 1;
    });
    child.on("error", (error) => {
      options.logger?.debug("Failed to run claude auth status", {
        error: error.message,
      });
      finish(false);
    });
    child.on("exit", (code) => {
      options.logger?.debug("claude auth status finished", {
        exitCode: code,
        outputLength,
      });
      finish(code === 0);
    });
  });
}
