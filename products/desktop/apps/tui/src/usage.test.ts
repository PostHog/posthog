import { stripTerminalSequences } from "@earendil-works/pi-tui";
import type { AgentConversationEvent, StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { contextFill, usageStatus } from "./usage";

const entry = (event: Partial<AgentConversationEvent>): StoredLogEntry => ({
  type: "pi_event",
  event: { timestamp: 0, ...event } as AgentConversationEvent,
});
const turn = (contextTokens: number | null, contextWindow?: number) =>
  entry({
    type: "turn_completed",
    usage: {
      inputTokens: 0,
      outputTokens: 0,
      cachedReadTokens: 0,
      cachedWriteTokens: 0,
      totalTokens: 1,
      contextTokens,
      contextWindow,
    },
  });
const compacted = entry({
  type: "runtime_status",
  status: "compacting",
  isComplete: true,
});

describe("contextFill", () => {
  it.each([
    ["no turns", [], null],
    [
      "the last turn",
      [turn(10, 100), turn(50, 200)],
      { tokens: 50, window: 200 },
    ],
    [
      "a window from an older turn",
      [turn(10, 100), turn(40)],
      { tokens: 40, window: 100 },
    ],
    ["a compaction since the last turn", [turn(10, 100), compacted], null],
    [
      "a turn after a compaction",
      [compacted, turn(5, 100)],
      { tokens: 5, window: 100 },
    ],
    ["a turn with no context tokens", [turn(10, 100), turn(null, 100)], null],
  ])("reads %s", (_, entries, expected) => {
    expect(contextFill(entries)).toEqual(expected);
  });
});

describe("usageStatus", () => {
  it.each([
    [null, null, ""],
    [null, 0, ""],
    [{ tokens: 10, window: 100 }, 0, "○"],
    [{ tokens: 0, window: 100 }, null, "○"],
    [{ tokens: 50, window: 100 }, 3.12, "◑ • $3.12"],
    [{ tokens: 100, window: 100 }, 0.001, "● • <$0.01"],
    [null, 12, "$12.00"],
  ])("draws %o and %o as %s", (fill, cost, expected) => {
    expect(stripTerminalSequences(usageStatus(fill, cost))).toBe(expected);
  });
});
