import { stripTerminalSequences } from "@earendil-works/pi-tui";
import type { AgentConversationEvent, StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { contextFill, isCompacting, shellsStatus, usageStatus } from "./usage";

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

describe("isCompacting", () => {
  const started = entry({ type: "runtime_status", status: "compacting" });
  const failed = entry({
    type: "runtime_status",
    status: "compacting_failed",
    error: "Summary failed",
  });

  it.each([
    ["no compaction", [turn(10, 100)], false],
    ["a compaction that has started", [turn(10, 100), started], true],
    ["a compaction that has finished", [started, compacted], false],
    ["a compaction that has failed", [started, failed], false],
    ["a new compaction after a finished one", [compacted, started], true],
  ])("reads %s", (_, entries, expected) => {
    expect(isCompacting(entries)).toBe(expected);
  });
});

const acpUsage = (used: number, size: number): StoredLogEntry => ({
  type: "acp_message",
  notification: {
    method: "session/update",
    params: { update: { sessionUpdate: "usage_update", used, size } },
  },
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
    [
      "a Claude Code usage update",
      [acpUsage(30, 200), acpUsage(60, 200)],
      { tokens: 60, window: 200 },
    ],
    ["a Claude Code usage update with no window", [acpUsage(60, 0)], null],
  ])("reads %s", (_, entries, expected) => {
    expect(contextFill(entries)).toEqual(expected);
  });
});

describe("usageStatus", () => {
  it.each([
    [null, null, "$0.00"],
    [null, 0, "$0.00"],
    [{ tokens: 10, window: 100 }, 0, "○ • $0.00"],
    [{ tokens: 0, window: 100 }, null, "○ • $0.00"],
    [{ tokens: 50, window: 100 }, 3.12, "◑ • $3.12"],
    [{ tokens: 100, window: 100 }, 0.001, "● • <$0.01"],
    [null, 12, "$12.00"],
    [{ tokens: 50, window: 100 }, { plan: "Claude Max" }, "◑ • Claude Max"],
    [null, { plan: "ChatGPT Plus" }, "ChatGPT Plus"],
  ])("draws %o and %o as %s", (fill, cost, expected) => {
    expect(stripTerminalSequences(usageStatus(fill, cost))).toBe(expected);
  });

  it("draws the cost faint, leaving only the donut in colour", () => {
    expect(usageStatus({ tokens: 50, window: 100 }, 3.12)).toMatch(
      new RegExp(`${"\u001b"}\\[2m • \\$3\\.12${"\u001b"}\\[22m$`),
    );
  });
});

describe("shellsStatus", () => {
  const status = (
    statusText: string | undefined,
    statusKey = "background-shells",
  ) =>
    ({
      type: "pi_extension_event",
      notification: {
        method: "_posthog/pi_extension_event",
        params: {
          type: "extension_ui_request",
          method: "setStatus",
          statusKey,
          statusText,
        },
      },
    }) as never;

  it.each([
    [
      "the latest status",
      [status("1 shell"), status("2 shells · 1 monitor")],
      "2 shells · 1 monitor",
    ],
    [
      "nothing once the shells are gone",
      [status("1 shell"), status(undefined)],
      undefined,
    ],
    [
      "nothing from another extension's status",
      [status("busy", "other")],
      undefined,
    ],
  ])("reads %s", (_, entries, expected) => {
    expect(shellsStatus(entries)).toBe(expected);
  });

  it("puts the shells before the context and cost", () => {
    expect(
      stripTerminalSequences(
        usageStatus({ tokens: 50, window: 100 }, 3.12, "2 shells · 1 monitor"),
      ),
    ).toBe("2 shells · 1 monitor • ◑ • $3.12");
  });
});
