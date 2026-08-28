import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import {
  applyMachineClaudeConfigDir,
  MACHINE_AUTH_STRIPPED_KEYS,
  machineClaudeAuthEnv,
} from "./machine-config-dir";

export type ClaudeAuthAction = "login" | "logout";

export interface ClaudeAuthTerminalCommand {
  /** Ready to run under `sh -c`. */
  command: string;
  env: { set: Record<string, string>; unset: string[] };
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

/**
 * The `claude auth` command to run in a terminal, and the env it needs.
 *
 * The CLI owns the whole OAuth flow: it opens the browser, prints the URL as a
 * fallback, and reads the paste-back code from the terminal. The app never
 * reads, copies, or stores the credentials. Sign-out is machine-wide, because
 * the login the terminal writes is the machine's own.
 */
export function claudeAuthTerminalCommand(
  action: ClaudeAuthAction,
  claudeCliPath: string,
): ClaudeAuthTerminalCommand {
  const args = action === "login" ? ["auth", "login"] : ["auth", "logout"];
  // The legacy CLI ships as cli.js and needs a JS runtime to start.
  const isLegacyJs = claudeCliPath.endsWith(".js");
  const parts = isLegacyJs
    ? [process.execPath, claudeCliPath, ...args]
    : [claudeCliPath, ...args];
  const env = machineClaudeAuthEnv();
  if (isLegacyJs && process.versions.electron) {
    env.set.ELECTRON_RUN_AS_NODE = "1";
  }
  return { command: parts.map(shellQuote).join(" "), env };
}

export interface ClaudeLoginCheckLogger {
  debug(message: string, ...args: unknown[]): void;
}

const STATUS_TIMEOUT_MS = 15_000;

export interface ClaudeLoginCheckOptions {
  /** Bundled Claude CLI path — must be the same binary sessions spawn. */
  claudeCliPath: string;
  logger?: ClaudeLoginCheckLogger;
  timeoutMs?: number;
}

/**
 * Whether this machine has a Claude Code login the CLI can use.
 *
 * Read-only by design: we never read, copy, or refresh provider credentials.
 * The check spawns `claude auth status` and reads only the exit code, using
 * the same credential-stripped env a machine-auth session gets, so the answer
 * matches what a session would actually authenticate with. The CLI owns the
 * credentials throughout, including in the in-app login terminal.
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
  // not make the check report an auth source sessions would not use, and the
  // login lives in the machine's config dir, not the app's.
  for (const key of MACHINE_AUTH_STRIPPED_KEYS) {
    delete env[key];
  }
  applyMachineClaudeConfigDir(env);
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

    // Stdout carries the account email and organization, so it is discarded
    // unread. Stderr carries the failure reason, so keep a bounded slice.
    let stderr = "";
    child.stdout?.on("data", () => {});
    child.stderr?.on("data", (chunk: Buffer) => {
      if (stderr.length < 500) stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => {
      options.logger?.debug("Failed to run claude auth status", {
        error: error.message,
      });
      finish(false);
    });
    child.on("exit", (code) => {
      options.logger?.debug("claude auth status finished", {
        claudeCliPath: options.claudeCliPath,
        exitCode: code,
        stderr: stderr.slice(0, 500),
      });
      finish(code === 0);
    });
  });
}
