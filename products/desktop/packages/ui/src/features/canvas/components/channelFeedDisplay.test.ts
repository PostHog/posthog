import type { SignalReport, Task } from "@posthog/shared/domain-types";
import type { ChannelFeedSystemMessage } from "@posthog/ui/features/canvas/hooks/useChannelFeedMessages";
import { describe, expect, it } from "vitest";
import { feedEntryMatchesKind, mergeFeedEntries } from "./channelFeedDisplay";

function task(id: string, createdAt: string): Task {
  return { id, created_at: createdAt } as Task;
}

function report(id: string, createdAt: string): SignalReport {
  return { id, created_at: createdAt } as SignalReport;
}

function system(id: string, createdAt: string): ChannelFeedSystemMessage {
  return { id, createdAt } as ChannelFeedSystemMessage;
}

describe("channelFeedDisplay", () => {
  it("interleaves reports with tasks and system rows newest-first", () => {
    const entries = mergeFeedEntries(
      [task("t1", "2026-01-02T00:00:00Z")],
      [system("s1", "2026-01-01T00:00:00Z")],
      [report("r1", "2026-01-03T00:00:00Z")],
    );
    expect(entries.map((e) => e.id)).toEqual(["r1", "t1", "s1"]);
  });

  it("keeps a tied task above its announcement with reports present", () => {
    const entries = mergeFeedEntries(
      [task("t1", "2026-01-01T00:00:00Z")],
      [system("s1", "2026-01-01T00:00:00Z")],
      [report("r1", "2026-01-01T00:00:00Z")],
    );
    expect(entries[0].id).toBe("t1");
  });

  it.each([
    ["all", ["task", "report", "system"]],
    ["sessions", ["task", "system"]],
    ["reports", ["report"]],
  ] as const)("kind filter %s keeps only %j", (filter, expectedKinds) => {
    const entries = mergeFeedEntries(
      [task("t1", "2026-01-03T00:00:00Z")],
      [system("s1", "2026-01-01T00:00:00Z")],
      [report("r1", "2026-01-02T00:00:00Z")],
    );
    const kept = entries
      .filter((entry) => feedEntryMatchesKind(entry, filter))
      .map((entry) => entry.kind);
    expect(kept).toEqual(expectedKinds);
  });
});
