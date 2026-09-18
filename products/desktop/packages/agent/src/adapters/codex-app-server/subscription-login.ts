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
  accountHome?: string;
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

export interface CodexLoginStatus {
  loggedIn: boolean;
  email?: string;
  planType?: string;
}

export interface CodexDeviceLoginSession {
  verificationUrl: string;
  userCode: string;
  completed: Promise<boolean>;
  cancel: () => Promise<void>;
}

export interface CodexSubscriptionTokens {
  accessToken: string;
  /** Codex rejects a `chatgptAuthTokens` login without this. */
  chatgptAccountId: string;
  chatgptPlanType?: string;
}

export interface CodexRateLimitWindow {
  usedPercent: number;
  windowDurationMins?: number;
  resetsAt?: string;
}

export interface CodexRateLimits {
  primary?: CodexRateLimitWindow;
  secondary?: CodexRateLimitWindow;
}

export async function hasCodexChatgptLogin(
  options: CodexAccountOptions,
): Promise<CodexLoginStatus> {
  const client = openCodexAccountClient(options);
  try {
    await initialize(client.rpc);
    const result = await requestWithTimeout<{
      account?: { type?: string; email?: string; planType?: string } | null;
    }>(client.rpc, APP_SERVER_METHODS.ACCOUNT_READ, { refreshToken: false });
    return {
      loggedIn: result.account?.type === "chatgpt",
      email: result.account?.email,
      planType: result.account?.planType,
    };
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
  const login = await startLoginSession<{ authUrl: string }>(options, {
    type: "chatgpt",
    useHostedLoginSuccessPage: true,
    appBrand: "chatgpt",
  });
  return {
    authUrl: login.reply.authUrl,
    completed: login.completed,
    cancel: login.cancel,
  };
}

/** Needs device code login on in ChatGPT settings, or an admin to allow it. */
export async function startCodexChatgptDeviceCodeLogin(
  options: CodexAccountOptions,
): Promise<CodexDeviceLoginSession> {
  const login = await startLoginSession<{
    verificationUrl: string;
    userCode: string;
  }>(options, { type: "chatgptDeviceCode" });
  return {
    verificationUrl: login.reply.verificationUrl,
    userCode: login.reply.userCode,
    completed: login.completed,
    cancel: login.cancel,
  };
}

export async function readCodexChatgptTokens(
  options: CodexAccountOptions & { force?: boolean },
): Promise<CodexSubscriptionTokens | null> {
  const client = openCodexAccountClient(options);
  try {
    await initialize(client.rpc);
    const status = await requestWithTimeout<{
      authMethod?: string;
      authToken?: string | null;
    }>(client.rpc, APP_SERVER_METHODS.GET_AUTH_STATUS, {
      includeToken: true,
      refreshToken: options.force ?? true,
    });
    if (!status.authToken) return null;
    const chatgptAccountId = chatgptAccountIdFromToken(status.authToken);
    if (!chatgptAccountId) return null;
    const account = await requestWithTimeout<{
      account?: { planType?: string } | null;
    }>(client.rpc, APP_SERVER_METHODS.ACCOUNT_READ, {
      refreshToken: false,
    }).catch(() => ({ account: null }));
    return {
      accessToken: status.authToken,
      chatgptAccountId,
      chatgptPlanType: account.account?.planType,
    };
  } finally {
    client.close();
  }
}

export async function readCodexRateLimits(
  options: CodexAccountOptions,
): Promise<CodexRateLimits | null> {
  const client = openCodexAccountClient(options);
  try {
    await initialize(client.rpc);
    const limits = await requestWithTimeout<{
      rateLimits?: CodexRateLimits | null;
    }>(client.rpc, APP_SERVER_METHODS.ACCOUNT_RATE_LIMITS_READ, {});
    return limits.rateLimits ?? null;
  } catch {
    return null;
  } finally {
    client.close();
  }
}

/** `account/read` does not report the workspace id, so read it off the token. */
function chatgptAccountIdFromToken(accessToken: string): string | undefined {
  const payload = accessToken.split(".")[1];
  if (!payload) return undefined;
  try {
    const claims: unknown = JSON.parse(
      Buffer.from(payload, "base64url").toString("utf8"),
    );
    if (typeof claims !== "object" || claims === null) return undefined;
    const auth = Reflect.get(claims, "https://api.openai.com/auth");
    if (typeof auth !== "object" || auth === null) return undefined;
    const accountId = Reflect.get(auth, "chatgpt_account_id");
    return typeof accountId === "string" ? accountId : undefined;
  } catch {
    return undefined;
  }
}

interface StartedLoginSession<TReply> {
  reply: TReply;
  completed: Promise<boolean>;
  cancel: () => Promise<void>;
}

async function startLoginSession<TReply>(
  options: CodexAccountOptions,
  params: Record<string, unknown>,
): Promise<StartedLoginSession<TReply>> {
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
    const login = await requestWithTimeout<TReply & { loginId: string }>(
      client.rpc,
      APP_SERVER_METHODS.ACCOUNT_LOGIN_START,
      params,
    );
    loginId = login.loginId;
    if (!settled) timeout = setTimeout(() => finish(false), LOGIN_TIMEOUT_MS);

    return {
      reply: login,
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
    accountHome: options.accountHome,
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
