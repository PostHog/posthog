import { describe, expect, it, vi } from "vitest";
import { GithubConnectService } from "./githubConnectService";
import type { GithubConnectClient } from "./identifiers";

function makeClient(
  disconnect: GithubConnectClient["disconnectGithubUserIntegration"] = vi
    .fn()
    .mockResolvedValue(undefined),
): GithubConnectClient {
  return { disconnectGithubUserIntegration: disconnect };
}

describe("GithubConnectService", () => {
  it("disconnects an installation through the client", async () => {
    const disconnect = vi.fn().mockResolvedValue(undefined);
    const service = new GithubConnectService(makeClient(disconnect));

    await service.disconnectInstallation("install-1");

    expect(disconnect).toHaveBeenCalledWith("install-1");
  });

  it("reconnect disconnects then runs the connect flow in order", async () => {
    const calls: string[] = [];
    const disconnect = vi.fn().mockImplementation(async () => {
      calls.push("disconnect");
    });
    const connect = vi.fn().mockImplementation(async () => {
      calls.push("connect");
    });
    const service = new GithubConnectService(makeClient(disconnect));

    await service.reconnectStaleInstallation("install-1", connect);

    expect(calls).toEqual(["disconnect", "connect"]);
  });

  it("reports the in-flight installation while reconnecting", async () => {
    let resolveDisconnect: () => void = () => undefined;
    const disconnect = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveDisconnect = resolve;
        }),
    );
    const service = new GithubConnectService(makeClient(disconnect));

    const pending = service.reconnectStaleInstallation(
      "install-1",
      vi.fn().mockResolvedValue(undefined),
    );

    expect(service.isReconnecting("install-1")).toBe(true);
    expect(service.isReconnecting("install-2")).toBe(false);
    expect(service.isAnyReconnectInFlight()).toBe(true);

    resolveDisconnect();
    await pending;

    expect(service.isAnyReconnectInFlight()).toBe(false);
  });

  it("refuses a second reconnect while one is in flight", async () => {
    let resolveDisconnect: () => void = () => undefined;
    const disconnect = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveDisconnect = resolve;
        }),
    );
    const connect = vi.fn().mockResolvedValue(undefined);
    const service = new GithubConnectService(makeClient(disconnect));

    const first = service.reconnectStaleInstallation("install-1", connect);
    await service.reconnectStaleInstallation("install-2", connect);

    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(disconnect).toHaveBeenCalledWith("install-1");

    resolveDisconnect();
    await first;
  });

  it("clears the gate even when connect throws", async () => {
    const service = new GithubConnectService(makeClient());
    const connect = vi.fn().mockRejectedValue(new Error("boom"));

    await expect(
      service.reconnectStaleInstallation("install-1", connect),
    ).rejects.toThrow("boom");
    expect(service.isAnyReconnectInFlight()).toBe(false);
  });

  describe("shouldReportFailure", () => {
    it("reports a fingerprint once then dedups it", () => {
      const service = new GithubConnectService(makeClient());

      expect(service.shouldReportFailure("error")).toBe(true);
      expect(service.shouldReportFailure("error")).toBe(false);
    });

    it("reports a changed fingerprint again", () => {
      const service = new GithubConnectService(makeClient());

      expect(service.shouldReportFailure("timeout")).toBe(true);
      expect(service.shouldReportFailure("error")).toBe(true);
    });

    it("clears tracking on a null fingerprint so the next failure reports", () => {
      const service = new GithubConnectService(makeClient());

      service.shouldReportFailure("error");
      expect(service.shouldReportFailure(null)).toBe(false);
      expect(service.shouldReportFailure("error")).toBe(true);
    });
  });
});
