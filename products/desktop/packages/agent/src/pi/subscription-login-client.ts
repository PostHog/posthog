import { type ChildProcess, fork } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import type {
  PiSubscriptionLoginState,
  PiSubscriptionProvider,
} from "@posthog/shared";
import { safePiEnvironment } from "./rpc-environment";

export type { PiSubscriptionLoginState, PiSubscriptionProvider };

const REQUEST_TIMEOUT_MS = 15_000;
const LOGIN_TIMEOUT_MS = 10 * 60_000;
const MAX_CAPTURED_STDERR = 4_000;

interface HostResponse {
  id?: string;
  type: "response" | "error";
  data?: unknown;
  error?: string;
}

interface HostNotification {
  type: "login_completed";
  provider: PiSubscriptionProvider;
  loggedIn: boolean;
}

interface HostProcess {
  child: ChildProcess;
  getStderr: () => string;
  kill: () => void;
}

function spawnHost(): HostProcess {
  const hostPath = fileURLToPath(
    new URL("./subscription-login-host.js", import.meta.url),
  );
  const child = fork(hostPath, [], {
    stdio: ["ignore", "ignore", "pipe", "ipc"],
    env: {
      ...safePiEnvironment(process.env),
      // fork() spawns process.execPath, which under Electron is the Electron
      // binary itself. Without this, it launches another Electron instance
      // instead of running the script as plain Node (see rpc-client.ts and
      // adapters/claude/subscription-login.ts for the same requirement).
      ELECTRON_RUN_AS_NODE: "1",
    },
  });

  let stderr = "";
  child.stderr?.on("data", (chunk: Buffer) => {
    if (stderr.length < MAX_CAPTURED_STDERR) stderr += chunk.toString("utf8");
  });

  return {
    child,
    getStderr: () => stderr,
    kill: () => child.kill(),
  };
}

function exitError(host: HostProcess, code: number | null): Error {
  const stderr = host.getStderr().trim();
  return new Error(
    `Pi subscription login process exited unexpectedly (code ${code}).${
      stderr ? ` Stderr: ${stderr}` : ""
    }`,
  );
}

function sendRequest<T>(
  host: HostProcess,
  type: "status" | "login" | "logout" | "cancel",
  provider: PiSubscriptionProvider,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const id = randomUUID();
  const { child } = host;
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("Pi subscription request timed out"));
    }, timeoutMs);

    const onMessage = (message: unknown) => {
      const response = message as Partial<HostResponse>;
      if (response.id !== id) return;
      cleanup();
      if (response.type === "error") {
        reject(new Error(response.error ?? "Pi subscription request failed"));
      } else {
        resolve(response.data as T);
      }
    };
    const onExit = (code: number | null) => {
      cleanup();
      reject(exitError(host, code));
    };
    const onError = (error: Error) => {
      cleanup();
      reject(error);
    };
    const cleanup = (): void => {
      clearTimeout(timer);
      child.off("message", onMessage);
      child.off("exit", onExit);
      child.off("error", onError);
    };

    child.on("message", onMessage);
    child.once("exit", onExit);
    child.once("error", onError);
    child.send({ id, type, provider });
  });
}

export async function piSubscriptionLoginState(
  provider: PiSubscriptionProvider,
): Promise<PiSubscriptionLoginState> {
  const host = spawnHost();
  try {
    const { loginState } = await sendRequest<{
      loginState: PiSubscriptionLoginState;
    }>(host, "status", provider);
    return loginState;
  } catch {
    return "unknown";
  } finally {
    host.kill();
  }
}

export async function signOutPiSubscription(
  provider: PiSubscriptionProvider,
): Promise<void> {
  const host = spawnHost();
  try {
    await sendRequest(host, "logout", provider);
  } finally {
    host.kill();
  }
}

export interface PiSubscriptionLoginSession {
  authUrl: string;
  completed: Promise<boolean>;
  cancel: () => Promise<void>;
}

export async function startPiSubscriptionLogin(
  provider: PiSubscriptionProvider,
): Promise<PiSubscriptionLoginSession> {
  const host = spawnHost();
  const { child } = host;
  let settled = false;

  const completed = new Promise<boolean>((resolve) => {
    const timeout = setTimeout(() => resolve(false), LOGIN_TIMEOUT_MS);
    const onMessage = (message: unknown) => {
      const notification = message as Partial<HostNotification>;
      if (
        notification.type !== "login_completed" ||
        notification.provider !== provider
      ) {
        return;
      }
      clearTimeout(timeout);
      child.off("message", onMessage);
      resolve(Boolean(notification.loggedIn));
    };
    child.on("message", onMessage);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolve(false);
    });
  }).finally(() => {
    settled = true;
    host.kill();
  });

  let authUrl: string;
  try {
    const response = await sendRequest<{ authUrl: string }>(
      host,
      "login",
      provider,
    );
    authUrl = response.authUrl;
  } catch (error) {
    host.kill();
    throw error;
  }

  return {
    authUrl,
    completed,
    // Idempotent, and bounded well under LOGIN_TIMEOUT_MS: tells the host to
    // abort (best effort, on its own short request timeout), then always
    // kills the child as a hard backstop regardless of whether that ack
    // arrived. That's what actually frees the OAuth callback port — callers
    // (AgentService) await this before starting a new login for the same
    // provider, so the two can't race for the port. Mirrors CodexLoginSession's
    // cancel() in ../adapters/codex-app-server/subscription-login.ts.
    cancel: async () => {
      if (settled) return;
      settled = true;
      await sendRequest(host, "cancel", provider).catch(() => undefined);
      host.kill();
    },
  };
}
