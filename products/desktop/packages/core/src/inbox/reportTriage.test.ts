import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import { groupReportsForTriage, reportTriageGroup } from "./reportTriage";

function report(overrides: Partial<SignalReport>): SignalReport {
  return {
    id: overrides.id ?? "r",
    title: "A report",
    summary: null,
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    artefact_count: 0,
    ...overrides,
  } as SignalReport;
}

describe("reportTriageGroup", () => {
  it.each([
    // Terminal states are the archive filter's job, not the page's.
    [{ status: "suppressed" }, null],
    [{ status: "resolved" }, null],
    [{ status: "deleted" }, null],
    // Waiting on a person.
    [{ status: "pending_input" }, "decision"],
    [{ status: "failed" }, "decision"],
    [{ status: "ready" }, "decision"],
    [{ status: "ready", actionability: "immediately_actionable" }, "decision"],
    // A PR outranks everything else the report could ask.
    [{ status: "ready", implementation_pr_url: "https://gh/pr/1" }, "review"],
    [
      { status: "in_progress", implementation_pr_url: "https://gh/pr/1" },
      "review",
    ],
    // Agent still working.
    [{ status: "potential" }, "in-progress"],
    [{ status: "candidate" }, "in-progress"],
    [{ status: "in_progress" }, "in-progress"],
    // Read-and-archive.
    [{ status: "ready", already_addressed: true }, "fyi"],
    [{ status: "ready", actionability: "not_actionable" }, "fyi"],
  ] as const)("%j triages to %s", (overrides, group) => {
    expect(reportTriageGroup(report(overrides as Partial<SignalReport>))).toBe(
      group,
    );
  });
});

describe("groupReportsForTriage", () => {
  it("orders each group by priority, then newest activity, unprioritized last", () => {
    const grouped = groupReportsForTriage([
      report({ id: "none", updated_at: "2026-06-05T00:00:00Z" }),
      report({
        id: "p2-old",
        priority: "P2",
        updated_at: "2026-06-01T00:00:00Z",
      }),
      report({ id: "p0", priority: "P0", updated_at: "2026-01-01T00:00:00Z" }),
      report({
        id: "p2-new",
        priority: "P2",
        updated_at: "2026-06-04T00:00:00Z",
      }),
      report({ id: "archived", status: "suppressed" }),
    ]);
    expect(grouped.decision.map((r) => r.id)).toEqual([
      "p0",
      "p2-new",
      "p2-old",
      "none",
    ]);
    expect(grouped.review).toEqual([]);
    expect(grouped.inProgress).toEqual([]);
    expect(grouped.fyi).toEqual([]);
  });
});
