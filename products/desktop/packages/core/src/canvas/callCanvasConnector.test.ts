import { afterEach, describe, expect, it, vi } from "vitest";
import { callCanvasConnector } from "./callCanvasConnector";
import type { CanvasConnectorCallResult } from "./dashboardSchemas";

const input = {
  provider: "mcp:calendar.example.com",
  tool: "list_events",
  arguments: { limit: 5 },
};
const success: CanvasConnectorCallResult = {
  status: "ok",
  result: {},
  detail: "",
  truncated: false,
  connect_path: null,
};
const approval: CanvasConnectorCallResult = {
  ...success,
  status: "needs_approval",
  approval_token: "server-issued-token",
};

describe("canvas connector approval and I/O", () => {
  afterEach(() => vi.useRealTimers());

  it.each(["initial", "approved"])(
    "times out stalled %s I/O and aborts the transport",
    async (phase) => {
      vi.useFakeTimers();
      const invoke = vi
        .fn<
          (
            token: string | undefined,
            signal: AbortSignal,
          ) => Promise<CanvasConnectorCallResult>
        >()
        .mockImplementation(() => new Promise(() => {}));
      if (phase === "approved") invoke.mockResolvedValueOnce(approval);
      const pending = callCanvasConnector(
        input,
        invoke,
        vi.fn().mockResolvedValue(true),
        new AbortController().signal,
      );
      const rejected = expect(pending).rejects.toThrow(
        "Canvas connector request timed out",
      );
      await vi.advanceTimersByTimeAsync(30_000);
      await rejected;
      expect(invoke).toHaveBeenCalledTimes(phase === "approved" ? 2 : 1);
      expect(invoke.mock.lastCall?.[1].aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("waits for the viewer without spending the I/O timeout or exposing the token", async () => {
    vi.useFakeTimers();
    let respond: (allowed: boolean) => void = () => {};
    const requestPermission = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          respond = resolve;
        }),
    );
    const invoke = vi
      .fn()
      .mockResolvedValueOnce(approval)
      .mockResolvedValueOnce({ ...success, approval_token: "private-token" });
    const pending = callCanvasConnector(
      input,
      invoke,
      requestPermission,
      new AbortController().signal,
    );
    const completed = vi.fn();
    void pending.then(completed);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(requestPermission).toHaveBeenCalledTimes(1);
    expect(invoke).toHaveBeenCalledTimes(1);
    expect(completed).not.toHaveBeenCalled();
    respond(true);
    const result = await pending;
    expect(result.status).toBe("ok");
    expect(result.approval_token).toBeUndefined();
    expect(invoke).toHaveBeenLastCalledWith(
      "server-issued-token",
      expect.any(AbortSignal),
    );
    expect(vi.getTimerCount()).toBe(0);
  });
});
