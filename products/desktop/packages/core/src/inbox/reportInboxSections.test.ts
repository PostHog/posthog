import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import { partitionInboxReports } from "./reportInboxSections";

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

describe("reportInboxSections", () => {
  it.each([
    // The boundary is status alone — the one dimension server counts can
    // reproduce. Ready is a decision whatever else the report carries...
    [{ status: "ready" }, "decision"],
    [{ status: "ready", actionability: "not_actionable" }, "decision"],
    [{ status: "ready", already_addressed: true }, "decision"],
    [
      {
        status: "ready",
        implementation_pr_url: "https://gh/pr/9",
        implementation_pr_merged: true,
      },
      "decision",
    ],
    [{ status: "pending_input" }, "attention"],
    [{ status: "failed" }, "attention"],
    [{ status: "in_progress" }, "inProgress"],
    [
      { status: "in_progress", implementation_pr_url: "https://gh/pr/1" },
      "inProgress",
    ],
    [{ status: "candidate" }, "inProgress"],
  ] as const)("%j lands in %s", (overrides, section) => {
    const sections = partitionInboxReports([
      report(overrides as Partial<SignalReport>),
    ]);
    expect(sections.decision.length).toBe(section === "decision" ? 1 : 0);
    expect(sections.attention.length).toBe(section === "attention" ? 1 : 0);
    expect(sections.inProgress.length).toBe(section === "inProgress" ? 1 : 0);
  });

  it("partition preserves the list's own order within each section", () => {
    const sections = partitionInboxReports([
      report({ id: "d1" }),
      report({ id: "a1", status: "pending_input" }),
      report({ id: "d2" }),
      report({ id: "p1", status: "candidate" }),
    ]);
    expect(sections.decision.map((r) => r.id)).toEqual(["d1", "d2"]);
    expect(sections.attention.map((r) => r.id)).toEqual(["a1"]);
    expect(sections.inProgress.map((r) => r.id)).toEqual(["p1"]);
  });
});
