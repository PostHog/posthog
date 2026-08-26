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
  authUrl: string;
  /** True when an account is signed in; false on timeout, cancel, or exit. */
  completed: Promise<boolean>;
  cancel: () => void;
}

// account/read is the stable auth check across codex versions.
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
      // The app-server exited or closed the stream.
      return false;
    }
    await sleep(pollIntervalMs, options.signal);
  }
  return false;
}

// The app-server hosts the OAuth callback. Keep it alive until `completed` settles.
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
