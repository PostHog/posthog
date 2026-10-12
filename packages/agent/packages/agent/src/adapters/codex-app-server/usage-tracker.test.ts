import { describe, expect, it } from "vitest";
import { UsageTracker } from "./usage-tracker";

function payload(overrides?: Record<string, unknown>) {
  return {
    tokenUsage: {
      total: {
        inputTokens: 900,
        cachedInputTokens: 100,
        outputTokens: 200,
        reasoningOutputTokens: 40,
        totalTokens: 1200,
      },
      last: {
        inputTokens: 400,
        cachedInputTokens: 50,
        outputTokens: 80,
        reasoningOutputTokens: 20,
        totalTokens: 500,
      },
      modelContextWindow: 200_000,
      ...overrides,
    },
  };
}

describe("UsageTracker", () => {
  it("starts with the latest request without counting a resumed thread's history", () => {
    const tracker = new UsageTracker();
    const update = tracker.ingest(payload());

    expect(update).toEqual({
      used: 500,
      size: 200_000,
      usage: {
        inputTokens: 400,
        outputTokens: 80,
        cachedReadTokens: 50,
        reasoningTokens: 20,
        totalTokens: 500,
      },
    });
    expect(tracker.contextTokens()).toBe(500);
    expect(tracker.perTurnUsage()).toEqual({
      inputTokens: 400,
      outputTokens: 80,
      cachedReadTokens: 50,
      cachedWriteTokens: 0,
      thoughtTokens: 20,
      totalTokens: 480,
    });
  });

  it("falls back to `total` for builds predating `last`", () => {
    const tracker = new UsageTracker();
    const update = tracker.ingest(payload({ last: undefined }));

    expect(update?.used).toBe(1200);
    expect(tracker.perTurnUsage()?.inputTokens).toBe(900);
  });

  it("derives `used` from inputTokens when totalTokens is absent (same order as the gauge)", () => {
    const tracker = new UsageTracker();
    const update = tracker.ingest({
      tokenUsage: { last: { inputTokens: 300 }, total: { inputTokens: 300 } },
    });

    expect(update?.used).toBe(300);
    expect(update?.size).toBeNull();
    expect(tracker.contextTokens()).toBe(300);
  });

  it("returns null and keeps state on an unusable payload", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());

    expect(tracker.ingest({})).toBeNull();
    expect(tracker.ingest({ tokenUsage: {} })).toBeNull();
    expect(tracker.ingest(undefined)).toBeNull();
    expect(tracker.contextTokens()).toBe(500);
  });

  it("sums model requests once, even when equal requests or repeated updates arrive", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());

    const next = payload({
      total: {
        inputTokens: 1000,
        cachedInputTokens: 110,
        outputTokens: 220,
        reasoningOutputTokens: 45,
      },
      last: {
        inputTokens: 100,
        cachedInputTokens: 10,
        outputTokens: 20,
        reasoningOutputTokens: 5,
        totalTokens: 130,
      },
    });
    tracker.ingest(next);
    tracker.ingest(next);

    expect(tracker.perTurnUsage()).toEqual({
      inputTokens: 500,
      outputTokens: 100,
      cachedReadTokens: 60,
      cachedWriteTokens: 0,
      thoughtTokens: 25,
      totalTokens: 600,
    });
    expect(tracker.contextTokens()).toBe(130);
    tracker.ingest(
      payload({
        ...next.tokenUsage,
        total: {
          inputTokens: 1100,
          cachedInputTokens: 120,
          outputTokens: 240,
          reasoningOutputTokens: 50,
        },
      }),
    );
    expect(tracker.perTurnUsage()).toMatchObject({
      inputTokens: 600,
      outputTokens: 120,
      totalTokens: 720,
    });
  });

  it("keeps a copy of accumulated usage when the continuation reports none", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());

    expect(tracker.perTurnUsage()).toEqual({
      inputTokens: 400,
      outputTokens: 80,
      cachedReadTokens: 50,
      cachedWriteTokens: 0,
      thoughtTokens: 20,
      totalTokens: 480,
    });
    const returned = tracker.perTurnUsage();
    if (returned) returned.inputTokens = 0;
    expect(tracker.perTurnUsage()?.inputTokens).toBe(400);
  });

  it("clears per-turn usage but retains the cumulative baseline for a follow-up", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());

    tracker.resetForTurn();
    expect(tracker.contextTokens()).toBeUndefined();
    expect(tracker.perTurnUsage()).toBeUndefined();
    tracker.ingest(
      payload({
        total: {
          inputTokens: 1100,
          cachedInputTokens: 120,
          outputTokens: 250,
          reasoningOutputTokens: 45,
        },
        last: { inputTokens: 100, outputTokens: 20 },
      }),
    );
    expect(tracker.perTurnUsage()).toEqual({
      inputTokens: 200,
      outputTokens: 50,
      cachedReadTokens: 20,
      cachedWriteTokens: 0,
      thoughtTokens: 5,
      totalTokens: 250,
    });
  });

  it("ignores compaction context estimates and counts subsequent model requests", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());
    tracker.ingest(payload({ last: { totalTokens: 2000 } }));
    expect(tracker.contextTokens()).toBe(2000);
    expect(tracker.perTurnUsage()?.totalTokens).toBe(480);
    tracker.ingest(
      payload({
        total: {
          inputTokens: 950,
          cachedInputTokens: 100,
          outputTokens: 220,
          reasoningOutputTokens: 40,
        },
        last: { inputTokens: 50, outputTokens: 20, totalTokens: 70 },
      }),
    );
    expect(tracker.perTurnUsage()).toMatchObject({
      inputTokens: 450,
      outputTokens: 100,
      totalTokens: 550,
    });
  });

  it("rebases reset counters without counting synthetic context-window tokens", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());
    tracker.ingest(
      payload({
        total: { totalTokens: 200_000 },
        last: { totalTokens: 200_000 },
      }),
    );
    tracker.ingest(
      payload({
        total: { inputTokens: 50, outputTokens: 20 },
        last: { inputTokens: 50, outputTokens: 20 },
      }),
    );
    expect(tracker.perTurnUsage()).toMatchObject({
      inputTokens: 450,
      outputTokens: 100,
      totalTokens: 550,
    });
  });

  it("counts last-only updates without recounting them when totals return", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());
    tracker.ingest(
      payload({
        total: undefined,
        last: { inputTokens: 50, outputTokens: 20 },
      }),
    );
    tracker.ingest(
      payload({
        total: { inputTokens: 1000, outputTokens: 240 },
        last: { inputTokens: 50, outputTokens: 20 },
      }),
    );
    expect(tracker.perTurnUsage()).toMatchObject({
      inputTokens: 500,
      outputTokens: 120,
      totalTokens: 620,
    });
  });

  it("does not carry a previous thread's baseline into a new session", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());
    tracker.resetForThread();
    tracker.ingest(
      payload({
        total: { inputTokens: 1500, outputTokens: 300 },
        last: { inputTokens: 100, outputTokens: 20 },
      }),
    );
    expect(tracker.perTurnUsage()).toMatchObject({
      inputTokens: 100,
      outputTokens: 20,
      totalTokens: 120,
    });
  });
});
