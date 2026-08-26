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
