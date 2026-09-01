import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import {
  applyMachineClaudeConfigDir,
  MACHINE_AUTH_STRIPPED_KEYS,
  machineClaudeAuthEnv,
} from "./machine-config-dir";

export type ClaudeAuthAction = "login" | "logout";

export interface ClaudeAuthTerminalCommand {
  command: string;
  env: { set: Record<string, string>; unset: string[] };
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

export function claudeAuthTerminalCommand(
  action: ClaudeAuthAction,
  claudeCliPath: string,
): ClaudeAuthTerminalCommand {
  const args = action === "login" ? ["auth", "login"] : ["auth", "logout"];
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
  claudeCliPath: string;
  logger?: ClaudeLoginCheckLogger;
  timeoutMs?: number;
}

export async function hasClaudeLogin(
  options: ClaudeLoginCheckOptions,
): Promise<boolean> {
  if (!existsSync(options.claudeCliPath)) {
    options.logger?.debug("Claude CLI not found, reporting no login", {
      claudeCliPath: options.claudeCliPath,
    });
    return false;
  }

  const isLegacyJs = options.claudeCliPath.endsWith(".js");
  const command = isLegacyJs ? process.execPath : options.claudeCliPath;
  const args = isLegacyJs
    ? [options.claudeCliPath, "auth", "status"]
    : ["auth", "status"];

  const env: NodeJS.ProcessEnv = { ...process.env };
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
