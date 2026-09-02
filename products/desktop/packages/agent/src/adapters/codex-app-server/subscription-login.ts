import type { ProcessSpawnedCallback } from "../../types";
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
import {
  type CodexAppServerProcess,
  spawnCodexAppServerProcess,
} from "./spawn";

const LOGIN_TIMEOUT_MS = 10 * 60 * 1000;
const REQUEST_TIMEOUT_MS = 10_000;

interface CodexAccountOptions {
  binaryPath: string;
  logger?: Logger;
  processCallbacks?: ProcessSpawnedCallback;
}

interface CodexAccountClient {
  process: CodexAppServerProcess;
  rpc: AppServerRpc;
  close: () => void;
}

export interface CodexLoginSession {
  authUrl: string;
  completed: Promise<boolean>;
  cancel: () => Promise<void>;
}

export async function hasCodexChatgptLogin(
  options: CodexAccountOptions,
): Promise<boolean> {
  const client = openCodexAccountClient(options);
  try {
    await initialize(client.rpc);
    const result = await requestWithTimeout<{
      account?: { type?: string } | null;
    }>(client.rpc, APP_SERVER_METHODS.ACCOUNT_READ, { refreshToken: false });
    return result.account?.type === "chatgpt";
  } finally {
    client.close();
  }
}

export async function signOutCodexChatgpt(
  options: CodexAccountOptions,
): Promise<void> {
  const client = openCodexAccountClient(options);
  try {
    await initialize(client.rpc);
    await requestWithTimeout(client.rpc, APP_SERVER_METHODS.ACCOUNT_LOGOUT, {});
  } finally {
    client.close();
  }
}

export async function startCodexChatgptLogin(
  options: CodexAccountOptions,
): Promise<CodexLoginSession> {
  let loginId: string | undefined;
  let settled = false;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let resolveCompleted: (value: boolean) => void = () => {};

  const completed = new Promise<boolean>((resolve) => {
    resolveCompleted = resolve;
  });
  const client = openCodexAccountClient(options, (method, params) => {
    if (method !== APP_SERVER_NOTIFICATIONS.ACCOUNT_LOGIN_COMPLETED) return;
    if (params === null || typeof params !== "object") return;
    const completedLoginId = Reflect.get(params, "loginId");
    const success = Reflect.get(params, "success");
    if (typeof completedLoginId !== "string" || typeof success !== "boolean") {
      return;
    }
    if (loginId !== undefined && completedLoginId !== loginId) return;
    finish(success);
  });

  function finish(success: boolean): void {
    if (settled) return;
    settled = true;
    if (timeout) clearTimeout(timeout);
    resolveCompleted(success);
    client.close();
  }

  client.process.process.once("exit", () => finish(false));

  try {
    await initialize(client.rpc);
    const login = await requestWithTimeout<{
      authUrl: string;
      loginId: string;
    }>(client.rpc, APP_SERVER_METHODS.ACCOUNT_LOGIN_START, {
      type: "chatgpt",
      useHostedLoginSuccessPage: true,
      appBrand: "chatgpt",
    });
    loginId = login.loginId;
    if (!settled) timeout = setTimeout(() => finish(false), LOGIN_TIMEOUT_MS);

    return {
      authUrl: login.authUrl,
      completed,
      cancel: async (): Promise<void> => {
        if (settled) return;
        await requestWithTimeout(
          client.rpc,
          APP_SERVER_METHODS.ACCOUNT_LOGIN_CANCEL,
          { loginId },
        ).catch(() => undefined);
        finish(false);
      },
    };
  } catch (error) {
    finish(false);
    throw error;
  }
}

function openCodexAccountClient(
  options: CodexAccountOptions,
  onNotification?: (method: string, params: unknown) => void,
): CodexAccountClient {
  const process = spawnCodexAppServerProcess({
    binaryPath: options.binaryPath,
    logger: options.logger,
    processCallbacks: options.processCallbacks,
    useMachineAuth: true,
  });
  const rpc = new AppServerClient(
    {
      readable: nodeReadableToWebReadable(process.stdout),
      writable: nodeWritableToWebWritable(process.stdin),
    },
    { logger: options.logger, onNotification },
  );
  let closed = false;
  return {
    process,
    rpc,
    close: (): void => {
      if (closed) return;
      closed = true;
      void rpc.close();
      process.kill();
    },
  };
}

async function initialize(rpc: AppServerRpc): Promise<void> {
  await requestWithTimeout(rpc, APP_SERVER_METHODS.INITIALIZE, {
    clientInfo: CODEX_CLIENT_INFO,
  });
  rpc.notify(APP_SERVER_NOTIFICATIONS.INITIALIZED, {});
}

async function requestWithTimeout<T = unknown>(
  rpc: AppServerRpc,
  method: string,
  params: unknown,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () => reject(new Error("The Codex account request timed out.")),
      REQUEST_TIMEOUT_MS,
    );
  });
  try {
    return await Promise.race([rpc.request<T>(method, params), timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
