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
  it("ingests `last` field-by-field, preferring it over cumulative `total`", () => {
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
      totalTokens: 500,
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

  it("resetForTurn clears stale per-turn usage", () => {
    const tracker = new UsageTracker();
    tracker.ingest(payload());

    tracker.resetForTurn();
    expect(tracker.contextTokens()).toBeUndefined();
    expect(tracker.perTurnUsage()).toBeUndefined();
  });
});
