import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentBootTracker } from "./boot-phases";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentBootTracker", () => {
  it("records named phases and a ready terminal state", async () => {
    vi.spyOn(performance, "now")
      .mockReturnValueOnce(100)
      .mockReturnValueOnce(110)
      .mockReturnValueOnce(135)
      .mockReturnValueOnce(150)
      .mockReturnValueOnce(500);

    const tracker = new AgentBootTracker("run-1");
    await tracker.measure("context_fetch", async () => "ok");
    tracker.markReady();

    expect(tracker.snapshot()).toEqual({
      contractVersion: 1,
      bootId: "run-1",
      state: "ready",
      totalMs: 50,
      phasesMs: { context_fetch: 25 },
    });
  });

  it("attributes failures to the active phase without exposing the error", async () => {
    vi.spyOn(performance, "now")
      .mockReturnValueOnce(10)
      .mockReturnValueOnce(20)
      .mockReturnValueOnce(45)
      .mockReturnValueOnce(50)
      .mockReturnValueOnce(500);

    const tracker = new AgentBootTracker("run-2");
    await expect(
      tracker.measure("acp_initialize", async () => {
        throw new Error("sensitive provider response");
      }),
    ).rejects.toThrow("sensitive provider response");
    tracker.markFailed();

    expect(tracker.snapshot()).toEqual({
      contractVersion: 1,
      bootId: "run-2",
      state: "failed",
      failedPhase: "acp_initialize",
      totalMs: 40,
      phasesMs: { acp_initialize: 25 },
    });
  });
});
