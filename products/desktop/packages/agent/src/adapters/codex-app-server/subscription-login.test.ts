import { beforeEach, describe, expect, it, vi } from "vitest";
import { APP_SERVER_METHODS, APP_SERVER_NOTIFICATIONS } from "./protocol";

const state = vi.hoisted(() => ({
  account: null as { type: string } | null,
  failLogout: false,
  kill: vi.fn(),
  onExit: undefined as (() => void) | undefined,
  onNotification: undefined as
    | ((method: string, params: unknown) => void)
    | undefined,
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

    async request(method: string): Promise<unknown> {
      state.requests.push(method);
      if (method === APP_SERVER_METHODS.ACCOUNT_READ) {
        return { account: state.account };
      }
      if (method === APP_SERVER_METHODS.ACCOUNT_LOGIN_START) {
        return {
          authUrl: "https://chatgpt.com/login",
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
  signOutCodexChatgpt,
  startCodexChatgptLogin,
} from "./subscription-login";

const options = { binaryPath: "/bundle/codex" };

beforeEach(() => {
  state.account = null;
  state.failLogout = false;
  state.kill.mockClear();
  state.onExit = undefined;
  state.onNotification = undefined;
  state.requests = [];
  state.spawnOptions = undefined;
});

describe("Codex account", () => {
  it("uses the normal machine login and accepts only ChatGPT accounts", async () => {
    state.account = { type: "chatgpt" };

    await expect(hasCodexChatgptLogin(options)).resolves.toBe(true);
    expect(state.spawnOptions?.useMachineAuth).toBe(true);

    state.account = { type: "apiKey" };
    await expect(hasCodexChatgptLogin(options)).resolves.toBe(false);
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

  it("reports a logout failure", async () => {
    state.failLogout = true;

    await expect(signOutCodexChatgpt(options)).rejects.toThrow("Logout failed");
  });
});
