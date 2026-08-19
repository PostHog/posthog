import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import { partitionReportSessions } from "./reportSessions";

function report(overrides: Partial<SignalReport>): SignalReport {
  return {
    id: "report",
    title: "Report",
    summary: "Summary",
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    artefact_count: 0,
    ...overrides,
  };
}

describe("partitionReportSessions", () => {
  it("keeps every former inbox state in its report-space section", () => {
    const reports = [
      report({ id: "active" }),
      report({ id: "run", status: "in_progress" }),
      report({
        id: "pull",
        implementation_pr_url: "https://github.com/posthog/posthog/pull/1",
      }),
      report({ id: "archived", status: "suppressed" }),
    ];

    expect(partitionReportSessions(reports)).toEqual({
      reports: [reports[0]],
      runs: [reports[1]],
      pulls: [reports[2]],
      archive: [reports[3]],
    });
  });
});
