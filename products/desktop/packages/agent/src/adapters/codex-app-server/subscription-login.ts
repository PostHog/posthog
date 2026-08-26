import type { Logger } from "../../utils/logger";
import {
  nodeReadableToWebReadable,
  nodeWritableToWebWritable,
} from "../../utils/streams";
import { AppServerClient, type AppServerRpc } from "./app-server-client";
import {
  APP_SERVER_METHODS,
  APP_SERVER_NOTIFICATIONS,
  CODEX_CLIENT_INFO,
} from "./protocol";
import { spawnCodexAppServerProcess } from "./spawn";

const LOGIN_TIMEOUT_MS = 10 * 60 * 1000;
const LOGIN_POLL_INTERVAL_MS = 2_000;

export interface CodexLoginSession {
  /** ChatGPT OAuth URL to open in the user's browser. */
  authUrl: string;
  /** Resolves true once codex reports a signed-in account; false on timeout, cancel, or process exit. */
  completed: Promise<boolean>;
  cancel: () => void;
}

/**
 * Polls `account/read` until codex reports a signed-in account. Polling is the
 * completion signal (rather than a login notification) because it reads the
 * authoritative auth state and survives protocol renames across codex versions.
 */
export async function waitForCodexAccount(
  rpc: AppServerRpc,
  options: {
    pollIntervalMs?: number;
    timeoutMs?: number;
    signal?: AbortSignal;
  } = {},
): Promise<boolean> {
  const pollIntervalMs = options.pollIntervalMs ?? LOGIN_POLL_INTERVAL_MS;
  const timeoutMs = options.timeoutMs ?? LOGIN_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline && !options.signal?.aborted) {
    try {
      const result = await rpc.request<{ account?: unknown }>(
        APP_SERVER_METHODS.ACCOUNT_READ,
        {},
      );
      if (result?.account) return true;
    } catch {
      // Client closed or the app-server process exited.
      return false;
    }
    await sleep(pollIntervalMs, options.signal);
  }
  return false;
}

/**
 * Runs Codex's own ChatGPT sign-in inside the given CODEX_HOME. The spawned
 * app-server hosts the OAuth callback, so it must stay alive until `completed`
 * settles. Tokens land in `<codexHome>/auth.json` (the spawn pins the file
 * credential store), so the login persists across app restarts.
 */
export async function startCodexChatgptLogin(options: {
  binaryPath: string;
  codexHome: string;
  logger?: Logger;
}): Promise<CodexLoginSession> {
  const proc = spawnCodexAppServerProcess({
    binaryPath: options.binaryPath,
    codexHome: options.codexHome,
    logger: options.logger,
  });
  const rpc = new AppServerClient(
    {
      readable: nodeReadableToWebReadable(proc.stdout),
      writable: nodeWritableToWebWritable(proc.stdin),
    },
    { logger: options.logger },
  );

  const abort = new AbortController();
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    abort.abort();
    void rpc.close();
    proc.kill();
  };

  try {
    await rpc.request(APP_SERVER_METHODS.INITIALIZE, {
      clientInfo: CODEX_CLIENT_INFO,
    });
    rpc.notify(APP_SERVER_NOTIFICATIONS.INITIALIZED, {});
    const login = await rpc.request<{ authUrl: string }>(
      APP_SERVER_METHODS.ACCOUNT_LOGIN_START,
      { type: "chatgpt" },
    );
    const completed = waitForCodexAccount(rpc, { signal: abort.signal });
    void completed.finally(dispose);
    return { authUrl: login.authUrl, completed, cancel: dispose };
  } catch (err) {
    dispose();
    throw err;
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms);
    function done() {
      signal?.removeEventListener("abort", done);
      clearTimeout(timer);
      resolve();
    }
    signal?.addEventListener("abort", done, { once: true });
  });
}
