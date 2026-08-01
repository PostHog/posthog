import type { StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  type CloudLogGapReconcileRequest,
  classifyCloudLogAppend,
  classifyCloudLogGap,
  mergeCloudLogGapRequests,
} from "./cloudLogGap";

function entry(line: string): StoredLogEntry {
  return {
    type: "notification",
    notification: { method: line },
  } as unknown as StoredLogEntry;
}

function request(
  over: Partial<CloudLogGapReconcileRequest> = {},
): CloudLogGapReconcileRequest {
  return {
    taskId: "t1",
    taskRunId: "r1",
    expectedCount: 10,
    currentCount: 5,
    newEntries: [],
    ...over,
  };
}

describe("mergeCloudLogGapRequests", () => {
  it("returns next when there is no current request", () => {
    const next = request();
    expect(mergeCloudLogGapRequests(undefined, next)).toBe(next);
  });

  it("widens the range and concatenates entries", () => {
    const current = request({
      currentCount: 3,
      expectedCount: 8,
      newEntries: [entry("a")],
      logUrl: "old",
    });
    const next = request({
      currentCount: 6,
      expectedCount: 12,
      newEntries: [entry("b")],
      logUrl: undefined,
    });

    const merged = mergeCloudLogGapRequests(current, next);
    expect(merged.currentCount).toBe(3);
    expect(merged.expectedCount).toBe(12);
    expect(merged.newEntries).toHaveLength(2);
    expect(merged.logUrl).toBe("old");
  });

  it("prefers next.logUrl when present", () => {
    const merged = mergeCloudLogGapRequests(
      request({ logUrl: "old" }),
      request({ logUrl: "new" }),
    );
    expect(merged.logUrl).toBe("new");
  });
});

describe("classifyCloudLogGap", () => {
  const base = {
    expectedCount: 10,
    latestCount: 0,
    totalLineCount: 0,
    parseFailureCount: 0,
    previousDeficiency: undefined,
  };

  it("is already-current when the store caught up", () => {
    expect(classifyCloudLogGap({ ...base, latestCount: 10 })).toEqual({
      kind: "already-current",
    });
  });

  it("fills when the fetch covered the expected count", () => {
    expect(classifyCloudLogGap({ ...base, totalLineCount: 12 })).toEqual({
      kind: "fill",
      processedLineCount: 12,
    });
  });

  it("commits best-effort on parse failures", () => {
    expect(
      classifyCloudLogGap({ ...base, totalLineCount: 7, parseFailureCount: 1 }),
    ).toEqual({
      kind: "commit-best-effort",
      processedLineCount: 10,
      reason: "parse-failure",
    });
  });

  it("commits best-effort on a stable repeated deficit", () => {
    expect(
      classifyCloudLogGap({
        ...base,
        totalLineCount: 7,
        previousDeficiency: { expectedCount: 10, observedLineCount: 7 },
      }),
    ).toEqual({
      kind: "commit-best-effort",
      processedLineCount: 10,
      reason: "stable-deficit",
    });
  });

  it("waits when short but the deficit is new (likely lag)", () => {
    expect(classifyCloudLogGap({ ...base, totalLineCount: 7 })).toEqual({
      kind: "wait",
      deficiency: { expectedCount: 10, observedLineCount: 7 },
    });
  });

  it("waits when the previous deficit differs from the current one", () => {
    expect(
      classifyCloudLogGap({
        ...base,
        totalLineCount: 7,
        previousDeficiency: { expectedCount: 10, observedLineCount: 5 },
      }),
    ).toMatchObject({ kind: "wait" });
  });
});

describe("classifyCloudLogAppend", () => {
  it("is caught up when the store already has the expected lines", () => {
    expect(classifyCloudLogAppend(5, 5, 3)).toEqual({ kind: "caught-up" });
  });

  it("is caught up when the store is ahead of the expected count", () => {
    expect(classifyCloudLogAppend(6, 5, 3)).toEqual({ kind: "caught-up" });
  });

  it("appends only the tail when the batch covers the gap", () => {
    expect(classifyCloudLogAppend(2, 5, 10)).toEqual({
      kind: "append-tail",
      tailCount: 3,
    });
  });

  it("appends the whole batch at the delta === available boundary", () => {
    expect(classifyCloudLogAppend(0, 3, 3)).toEqual({
      kind: "append-tail",
      tailCount: 3,
    });
  });

  it("reports a gap when the batch is one short of the delta", () => {
    expect(classifyCloudLogAppend(0, 4, 3)).toEqual({ kind: "gap" });
  });

  it("reports a gap when the batch cannot cover a large deficit", () => {
    expect(classifyCloudLogAppend(0, 100, 3)).toEqual({ kind: "gap" });
  });
});
