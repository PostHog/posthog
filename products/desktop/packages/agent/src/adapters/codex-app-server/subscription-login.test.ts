import { beforeEach, describe, expect, it, vi } from "vitest";
import { APP_SERVER_METHODS, APP_SERVER_NOTIFICATIONS } from "./protocol";

const state = vi.hoisted(() => ({
  account: null as { type: string; email?: string; planType?: string } | null,
  failLogout: false,
  kill: vi.fn(),
  onExit: undefined as (() => void) | undefined,
  onNotification: undefined as
    | ((method: string, params: unknown) => void)
    | undefined,
  authToken: null as string | null,
  loginParams: undefined as Record<string, unknown> | undefined,
  requests: [] as string[],
  spawnOptions: undefined as { useMachineAuth?: boolean } | undefined,
}));

vi.mock("./spawn", async () => {
  const { PassThrough } = await import("node:stream");
  return {
    spawnCodexAppServerProcess: (options: { useMachineAuth?: boolean }) => {
      state.spawnOptions = options;
      return {
        process: {
          once: (_event: string, callback: () => void) => {
            state.onExit = callback;
          },
        },
        stdout: new PassThrough(),
        stdin: new PassThrough(),
        kill: state.kill,
      };
    },
  };
});

vi.mock("./app-server-client", () => ({
  AppServerClient: class {
    constructor(
      _streams: unknown,
      handlers: {
        onNotification?: (method: string, params: unknown) => void;
      },
    ) {
      state.onNotification = handlers.onNotification;
    }

    async request(method: string, params?: unknown): Promise<unknown> {
      state.requests.push(method);
      if (method === APP_SERVER_METHODS.ACCOUNT_READ) {
        return { account: state.account };
      }
      if (method === APP_SERVER_METHODS.GET_AUTH_STATUS) {
        return { authMethod: "chatgpt", authToken: state.authToken };
      }
      if (method === APP_SERVER_METHODS.ACCOUNT_LOGIN_START) {
        state.loginParams = params as Record<string, unknown>;
        return {
          authUrl: "https://chatgpt.com/login",
          verificationUrl: "https://auth.openai.com/codex/device",
          userCode: "3JAD-AER05",
          loginId: "login-1",
        };
      }
      if (method === APP_SERVER_METHODS.ACCOUNT_LOGOUT && state.failLogout) {
        throw new Error("Logout failed");
      }
      return {};
    }

    notify(): void {}

    async close(): Promise<void> {}
  },
}));

import {
  hasCodexChatgptLogin,
  readCodexChatgptTokens,
  signOutCodexChatgpt,
  startCodexChatgptDeviceCodeLogin,
  startCodexChatgptLogin,
} from "./subscription-login";

function accessToken(claims: Record<string, unknown>): string {
  const encode = (value: unknown): string =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "RS256" })}.${encode(claims)}.signature`;
}

const options = { binaryPath: "/bundle/codex" };

beforeEach(() => {
  state.account = null;
  state.failLogout = false;
  state.kill.mockClear();
  state.onExit = undefined;
  state.onNotification = undefined;
  state.requests = [];
  state.spawnOptions = undefined;
  state.authToken = null;
  state.loginParams = undefined;
});

describe("Codex account", () => {
  it("uses the normal machine login and accepts only ChatGPT accounts", async () => {
    state.account = { type: "chatgpt" };

    await expect(hasCodexChatgptLogin(options)).resolves.toMatchObject({
      loggedIn: true,
    });
    expect(state.spawnOptions?.useMachineAuth).toBe(true);

    state.account = { type: "apiKey" };
    await expect(hasCodexChatgptLogin(options)).resolves.toMatchObject({
      loggedIn: false,
    });
  });

  it("surfaces the connected account's email and plan", async () => {
    state.account = {
      type: "chatgpt",
      email: "user@posthog.com",
      planType: "team",
    };

    await expect(hasCodexChatgptLogin(options)).resolves.toEqual({
      loggedIn: true,
      email: "user@posthog.com",
      planType: "team",
    });
  });

  it("finishes login from the app-server notification", async () => {
    const login = await startCodexChatgptLogin(options);

    expect(login.authUrl).toBe("https://chatgpt.com/login");
    state.onNotification?.(APP_SERVER_NOTIFICATIONS.ACCOUNT_LOGIN_COMPLETED, {
      loginId: "login-1",
      success: true,
    });

    await expect(login.completed).resolves.toBe(true);
    expect(state.requests).toEqual([
      APP_SERVER_METHODS.INITIALIZE,
      APP_SERVER_METHODS.ACCOUNT_LOGIN_START,
    ]);
  });

  it("cancels the active Codex login", async () => {
    const login = await startCodexChatgptLogin(options);

    await login.cancel();

    await expect(login.completed).resolves.toBe(false);
    expect(state.requests).toContain(APP_SERVER_METHODS.ACCOUNT_LOGIN_CANCEL);
  });

  it("starts a device-code login and returns the code to show", async () => {
    const login = await startCodexChatgptDeviceCodeLogin(options);

    expect(state.loginParams).toEqual({ type: "chatgptDeviceCode" });
    expect(login).toMatchObject({
      verificationUrl: "https://auth.openai.com/codex/device",
      userCode: "3JAD-AER05",
    });

    state.onNotification?.(APP_SERVER_NOTIFICATIONS.ACCOUNT_LOGIN_COMPLETED, {
      loginId: "login-1",
      success: true,
    });
    await expect(login.completed).resolves.toBe(true);
  });

  it("reads a live access token and the workspace it belongs to", async () => {
    state.account = { type: "chatgpt", planType: "pro" };
    state.authToken = accessToken({
      "https://api.openai.com/auth": { chatgpt_account_id: "workspace-7" },
    });

    await expect(readCodexChatgptTokens(options)).resolves.toEqual({
      accessToken: state.authToken,
      chatgptAccountId: "workspace-7",
      chatgptPlanType: "pro",
    });
    expect(state.requests).toContain(APP_SERVER_METHODS.GET_AUTH_STATUS);
  });

  it("returns nothing when codex holds no token", async () => {
    await expect(readCodexChatgptTokens(options)).resolves.toBeNull();
  });

  it("reports a logout failure", async () => {
    state.failLogout = true;

    await expect(signOutCodexChatgpt(options)).rejects.toThrow("Logout failed");
  });
});
