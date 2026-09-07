import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import {
  applyMachineClaudeAuth,
  type MachineClaudeAuth,
  machineClaudeAuthShellEnv,
} from "./machine-auth";

export type ClaudeAuthAction = "login" | "logout";

export interface ClaudeAuthTerminalCommand {
  command: string;
  env: { set: Record<string, string>; unset: string[] };
}

function shellQuote(value: string): string {
  if (process.platform === "win32") {
    return `"${value.replaceAll('"', '\\"')}"`;
  }
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

export function claudeAuthTerminalCommand(
  action: ClaudeAuthAction,
  claudeCliPath: string,
  machineAuth: MachineClaudeAuth,
): ClaudeAuthTerminalCommand {
  const args = action === "login" ? ["auth", "login"] : ["auth", "logout"];
  const isLegacyJs = claudeCliPath.endsWith(".js");
  const parts = isLegacyJs
    ? [process.execPath, claudeCliPath, ...args]
    : [claudeCliPath, ...args];
  const env = machineClaudeAuthShellEnv(machineAuth);
  if (isLegacyJs && process.versions.electron) {
    env.set.ELECTRON_RUN_AS_NODE = "1";
  }
  return { command: parts.map(shellQuote).join(" "), env };
}

export interface ClaudeLoginCheckLogger {
  debug(message: string, ...args: unknown[]): void;
}

const STATUS_TIMEOUT_MS = 15_000;
const STATUS_KILL_GRACE_MS = 2_000;

export interface ClaudeLoginCheckOptions {
  claudeCliPath: string;
  machineAuth: MachineClaudeAuth;
  logger?: ClaudeLoginCheckLogger;
  timeoutMs?: number;
}

export type ClaudeLoginResult = "logged-in" | "logged-out" | "unknown";

export interface ClaudeLoginStatus {
  state: ClaudeLoginResult;
  email?: string;
  organization?: string;
  subscriptionType?: string;
}

interface ClaudeAuthStatusJson {
  loggedIn?: unknown;
  authMethod?: unknown;
  apiProvider?: unknown;
  subscriptionType?: unknown;
  email?: unknown;
  orgName?: unknown;
}

function isSubscriptionLogin(status: ClaudeAuthStatusJson): boolean {
  if (status.loggedIn !== true) return false;
  const method = status.authMethod;
  return method === "claude.ai" || method === "oauth_token";
}

function accountFieldsFromStatus(
  status: ClaudeAuthStatusJson,
): Pick<ClaudeLoginStatus, "email" | "organization" | "subscriptionType"> {
  return {
    email: typeof status.email === "string" ? status.email : undefined,
    organization:
      typeof status.orgName === "string" ? status.orgName : undefined,
    subscriptionType:
      typeof status.subscriptionType === "string"
        ? status.subscriptionType
        : undefined,
  };
}

function parseAuthStatusJson(stdout: string): ClaudeAuthStatusJson | null {
  const trimmed = stdout.trim();
  if (!trimmed) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object") {
      return parsed as ClaudeAuthStatusJson;
    }
  } catch {}
  return null;
}

export async function hasClaudeLogin(
  options: ClaudeLoginCheckOptions,
): Promise<ClaudeLoginStatus> {
  if (!existsSync(options.claudeCliPath)) {
    options.logger?.debug("Claude CLI not found, reporting unknown", {
      claudeCliPath: options.claudeCliPath,
    });
    return { state: "unknown" };
  }

  const isLegacyJs = options.claudeCliPath.endsWith(".js");
  const command = isLegacyJs ? process.execPath : options.claudeCliPath;
  const args = isLegacyJs
    ? [options.claudeCliPath, "auth", "status", "--json"]
    : ["auth", "status", "--json"];

  const env: NodeJS.ProcessEnv = { ...process.env };
  applyMachineClaudeAuth(env, options.machineAuth);
  if (process.versions.electron || process.env.ELECTRON_RUN_AS_NODE) {
    env.ELECTRON_RUN_AS_NODE = "1";
  }

  return new Promise<ClaudeLoginStatus>((resolve) => {
    let settled = false;
    const finish = (result: ClaudeLoginStatus): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };

    const child = spawn(command, args, {
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      const killTimer = setTimeout(
        () => child.kill("SIGKILL"),
        STATUS_KILL_GRACE_MS,
      );
      child.once("exit", () => clearTimeout(killTimer));
      finish({ state: "unknown" });
    }, options.timeoutMs ?? STATUS_TIMEOUT_MS);

    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      if (stdout.length < 10_000) stdout += chunk.toString("utf8");
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      if (stderr.length < 500) stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => {
      options.logger?.debug("Failed to run claude auth status", {
        error: error.message,
      });
      finish({ state: "unknown" });
    });
    child.on("exit", (code) => {
      const status = parseAuthStatusJson(stdout);
      options.logger?.debug("claude auth status finished", {
        claudeCliPath: options.claudeCliPath,
        exitCode: code,
        authMethod: status?.authMethod ?? null,
        stderr: stderr.slice(0, 500),
      });
      if (status && isSubscriptionLogin(status)) {
        finish({ state: "logged-in", ...accountFieldsFromStatus(status) });
        return;
      }
      if (status || code === 0) {
        finish({ state: "logged-out" });
        return;
      }
      finish({ state: "unknown" });
    });
  });
}
