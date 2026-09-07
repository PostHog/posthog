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
    actionability: "immediately_actionable",
    ...overrides,
  } as SignalReport;
}

describe("reportInboxSections", () => {
  it.each([
    [{ status: "ready" }, "needsPr"],
    [
      {
        status: "ready",
        implementation_pr_url: "https://github.com/o/r/pull/1",
      },
      "reviewAndMerge",
    ],
    [{ status: "pending_input" }, "needsPr"],
    [{ status: "ready", actionability: "not_actionable" }, null],
    [
      {
        status: "pending_input",
        implementation_pr_url: "https://github.com/o/r/pull/2",
      },
      null,
    ],
    [{ status: "failed" }, null],
    [{ status: "in_progress" }, null],
    [{ status: "candidate" }, null],
  ] as const)("%j lands in %s", (overrides, section) => {
    const sections = partitionInboxReports([
      report(overrides as Partial<SignalReport>),
    ]);
    expect(sections.reviewAndMerge.length).toBe(
      section === "reviewAndMerge" ? 1 : 0,
    );
    expect(sections.needsPr.length).toBe(section === "needsPr" ? 1 : 0);
  });

  it("partition preserves the list's own order within each section", () => {
    const sections = partitionInboxReports([
      report({ id: "n1" }),
      report({ id: "r1", implementation_pr_url: "https://gh/pr/1" }),
      report({ id: "n2", status: "pending_input" }),
      report({ id: "r2", implementation_pr_url: "https://gh/pr/2" }),
    ]);
    expect(sections.reviewAndMerge.map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(sections.needsPr.map((r) => r.id)).toEqual(["n1", "n2"]);
  });
});
