import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppServerRpc } from "./app-server-client";
import { waitForCodexAccount } from "./subscription-login";

function fakeRpc(request: (method: string) => Promise<unknown>): AppServerRpc {
  return {
    request: request as AppServerRpc["request"],
    notify: () => {},
    close: async () => {},
  };
}

describe("waitForCodexAccount", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps polling while account is null and resolves true once it appears", async () => {
    let reads = 0;
    const rpc = fakeRpc(async () => {
      reads += 1;
      return { account: reads >= 3 ? { plan: "plus" } : null };
    });

    const result = waitForCodexAccount(rpc, {
      pollIntervalMs: 1000,
      timeoutMs: 60_000,
    });
    await vi.advanceTimersByTimeAsync(5000);

    await expect(result).resolves.toBe(true);
    expect(reads).toBe(3);
  });

  it("resolves false when the app-server dies mid-login instead of hanging", async () => {
    const rpc = fakeRpc(async () => {
      throw new Error("codex app-server stream closed");
    });

    await expect(
      waitForCodexAccount(rpc, { pollIntervalMs: 1000, timeoutMs: 60_000 }),
    ).resolves.toBe(false);
  });

  it("resolves false at the timeout when the user never finishes signing in", async () => {
    const rpc = fakeRpc(async () => ({ account: null }));

    const result = waitForCodexAccount(rpc, {
      pollIntervalMs: 1000,
      timeoutMs: 3000,
    });
    await vi.advanceTimersByTimeAsync(4000);

    await expect(result).resolves.toBe(false);
  });
});

describe("signOutCodexChatgpt", () => {
  async function setup() {
    vi.resetModules();
    const requests: Array<{ method: string }> = [];
    let failLogout = false;
    const rpc = {
      request: async (raw: unknown) => {
        const method =
          typeof raw === "string" ? raw : (raw as { method: string }).method;
        requests.push({ method });
        if (method === "account/logout" && failLogout) {
          throw new Error("logout failed");
        }
        return {};
      },
      notify: () => {},
      close: async () => {},
    };
    vi.doMock("./spawn", () => ({
      spawnCodexAppServerProcess: () => ({
        stdout: { on: () => {} },
        stdin: { on: () => {} },
        kill: () => {},
      }),
    }));
    vi.doMock("./app-server-client", () => ({
      AppServerClient: function () {
        return rpc;
      },
    }));
    const mod = await import("./subscription-login");
    return {
      requests,
      setFailLogout: (v: boolean) => {
        failLogout = v;
      },
      signOut: (opts: { binaryPath: string; codexHome: string }) =>
        mod.signOutCodexChatgpt(opts),
    };
  }

  it("initializes and calls account/logout, returning true on success", async () => {
    const { requests, signOut } = await setup();
    await expect(
      signOut({ binaryPath: "/sbin/codex", codexHome: "/home" }),
    ).resolves.toBe(true);
    expect(requests.map((r) => r.method)).toEqual([
      "initialize",
      "account/logout",
    ]);
  });

  it("returns false, without throwing, when the logout request fails", async () => {
    const { setFailLogout, signOut } = await setup();
    setFailLogout(true);
    await expect(
      signOut({ binaryPath: "/sbin/codex", codexHome: "/home" }),
    ).resolves.toBe(false);
  });
});
