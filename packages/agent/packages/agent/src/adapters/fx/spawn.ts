import { type ChildProcess, spawn } from "node:child_process";
import { once } from "node:events";
import type { Readable, Writable } from "node:stream";
import { setTimeout as delay } from "node:timers/promises";
import type { ProcessSpawnedCallback } from "../../types";
import type { Logger } from "../../utils/logger";
import { FX_GATEWAY_KEY_ENV, FX_PROVIDER_NAME } from "./settings";

export interface FxProcessOptions {
  binaryPath: string;
  cwd: string;
  model: string;
  gatewayKey: string;
  logger: Logger;
  processCallbacks?: ProcessSpawnedCallback;
}

export interface FxProcess {
  process: ChildProcess;
  stdin: Writable;
  stdout: Readable;
  kill: () => Promise<void>;
}

const KILL_GRACE_MS = 5_000;
const GROUP_POLL_MS = 50;

const SCRUBBED_ENV = [
  "AI_GATEWAY_API_KEY",
  "AI_GATEWAY_TOKEN",
  "VERCEL_OIDC_TOKEN",
  "OPENAI_API_KEY",
  "OPENAI_BASE_URL",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_BASE_URL",
  "POSTHOG_GATEWAY_API_KEY",
  "FX_REVIEW_MODEL",
  "FX_ULTRAFAST",
];

export function buildFxEnv(
  gatewayKey: string,
  environment: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...environment };
  for (const name of SCRUBBED_ENV) delete env[name];
  env[FX_GATEWAY_KEY_ENV] = gatewayKey;
  env.FX_PROVIDER = FX_PROVIDER_NAME;
  env.FX_PERMISSION_MODE = "ask";
  env.FX_AUTO_UPGRADE = "0";
  env.FX_NO_OPEN_BROWSER = "1";
  env.FX_HERDR = "0";
  return env;
}

function hasExited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

function signalProcessGroup(child: ChildProcess, signal: NodeJS.Signals): void {
  if (process.platform !== "win32" && child.pid) {
    try {
      process.kill(-child.pid, signal);
      return;
    } catch {}
  }
  if (!hasExited(child)) child.kill(signal);
}

function isGroupAlive(child: ChildProcess): boolean {
  if (process.platform === "win32" || !child.pid) return !hasExited(child);
  try {
    process.kill(-child.pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitForGroupExit(child: ChildProcess): Promise<boolean> {
  const deadline = Date.now() + KILL_GRACE_MS;
  while (isGroupAlive(child)) {
    if (Date.now() >= deadline) return false;
    await delay(GROUP_POLL_MS, undefined, { ref: false });
  }
  return true;
}

async function terminate(child: ChildProcess): Promise<void> {
  for (const signal of ["SIGTERM", "SIGKILL"] as const) {
    signalProcessGroup(child, signal);
    if (await waitForGroupExit(child)) break;
  }
  child.stdin?.destroy();
  child.stdout?.destroy();
  child.stderr?.destroy();
}

export async function spawnFxAcpProcess(
  options: FxProcessOptions,
): Promise<FxProcess> {
  const { logger } = options;
  const args = ["acp", "--model", options.model];
  logger.info("Spawning fx acp process", {
    command: options.binaryPath,
    args,
    cwd: options.cwd,
  });

  const child = spawn(options.binaryPath, args, {
    cwd: options.cwd,
    env: buildFxEnv(options.gatewayKey),
    stdio: ["pipe", "pipe", "pipe"],
    detached: process.platform !== "win32",
  });

  child.stderr?.on("data", (data: Buffer) => {
    logger.warn("fx acp stderr:", data.toString());
  });
  try {
    await once(child, "spawn");
  } catch (error) {
    throw new Error(
      `fx binary could not start (${options.binaryPath}). Install fx in the sandbox image or set POSTHOG_FX_BINARY_PATH.`,
      { cause: error },
    );
  }
  child.on("error", (error) => {
    logger.error("fx acp process error:", error);
  });
  child.on("exit", (code, signal) => {
    logger.info("fx acp process exited", { code, signal });
    if (child.pid) options.processCallbacks?.onProcessExited?.(child.pid);
  });

  if (!child.stdin || !child.stdout) {
    throw new Error("Failed to get stdio streams from fx acp process");
  }
  if (child.pid) {
    options.processCallbacks?.onProcessSpawned?.({
      pid: child.pid,
      command: options.binaryPath,
    });
  }
  const killOnServerExit = () => signalProcessGroup(child, "SIGKILL");
  process.once("exit", killOnServerExit);

  return {
    process: child,
    stdin: child.stdin,
    stdout: child.stdout,
    kill: async () => {
      await terminate(child);
      process.off("exit", killOnServerExit);
    },
  };
}
