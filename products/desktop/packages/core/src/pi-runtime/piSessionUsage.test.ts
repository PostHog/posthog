import type { PiSessionStats } from "@posthog/agent/pi/types";
import { describe, expect, it } from "vitest";
import { toPiContextUsage } from "./piSessionUsage";

function stats(
  contextUsage: PiSessionStats["contextUsage"],
  cost = 0,
): PiSessionStats {
  return {
    sessionFile: undefined,
    sessionId: "session-1",
    userMessages: 1,
    assistantMessages: 1,
    toolCalls: 0,
    toolResults: 0,
    totalMessages: 2,
    tokens: {
      input: 1_000,
      output: 500,
      cacheRead: 100,
      cacheWrite: 50,
      total: 1_650,
    },
    cost,
    contextUsage,
  };
}

describe("toPiContextUsage", () => {
  it("maps native Pi context and cost statistics to shared context usage", () => {
    expect(
      toPiContextUsage(
        stats(
          { tokens: 38_323, contextWindow: 1_000_000, percent: 3.8323 },
          0.42,
        ),
      ),
    ).toEqual({
      used: 38_323,
      size: 1_000_000,
      percentage: 4,
      cost: { amount: 0.42, currency: "USD" },
      breakdown: null,
      breakdownAvailable: false,
    });
  });

  it("hides context usage while Pi cannot estimate it", () => {
    expect(
      toPiContextUsage(
        stats({ tokens: null, contextWindow: 100_000, percent: null }),
      ),
    ).toBeNull();
  });
});
