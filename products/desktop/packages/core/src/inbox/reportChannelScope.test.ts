import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import {
  buildChannelReportList,
  channelReportView,
  countChannelReportsByStatus,
  countChannelReportsForMe,
  generalReportView,
} from "./reportChannelScope";

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

describe("reportChannelScope", () => {
  it("general view keeps reports from every space, including unassigned", () => {
    const reports = [
      report({ id: "a", channel_id: null }),
      report({ id: "b", channel_id: "space-1" }),
      report({ id: "c", channel_id: "space-2" }),
    ];
    const ids = buildChannelReportList(reports, {
      view: generalReportView(),
    }).map((r) => r.id);
    expect(ids).toEqual(["a", "b", "c"]);
  });

  it("channel view keeps only reports assigned to that space", () => {
    const reports = [
      report({ id: "a", channel_id: null }),
      report({ id: "b", channel_id: "space-1" }),
      report({ id: "c", channel_id: "space-2" }),
    ];
    const ids = buildChannelReportList(reports, {
      view: channelReportView("space-1"),
    }).map((r) => r.id);
    expect(ids).toEqual(["b"]);
  });

  it("drops suppressed, resolved, and deleted reports", () => {
    const reports = [
      report({ id: "keep", status: "ready" }),
      report({ id: "suppressed", status: "suppressed" }),
      report({ id: "resolved", status: "resolved" }),
      report({ id: "deleted", status: "deleted" }),
    ];
    const ids = buildChannelReportList(reports, {
      view: generalReportView(),
    }).map((r) => r.id);
    expect(ids).toEqual(["keep"]);
  });

  it("sorts newest first by updated_at", () => {
    const reports = [
      report({ id: "old", updated_at: "2026-01-01T00:00:00Z" }),
      report({ id: "new", updated_at: "2026-06-01T00:00:00Z" }),
    ];
    const ids = buildChannelReportList(reports, {
      view: generalReportView(),
    }).map((r) => r.id);
    expect(ids).toEqual(["new", "old"]);
  });

  it("relevantToMeOnly keeps only suggested-reviewer reports", () => {
    const reports = [
      report({ id: "mine", is_suggested_reviewer: true }),
      report({ id: "theirs", is_suggested_reviewer: false }),
    ];
    const ids = buildChannelReportList(reports, {
      view: generalReportView(),
      relevantToMeOnly: true,
    }).map((r) => r.id);
    expect(ids).toEqual(["mine"]);
  });

  it("search matches the title case-insensitively", () => {
    const reports = [
      report({ id: "flags", title: "Fix flag evaluation" }),
      report({ id: "cohorts", title: "Cohort query bug" }),
    ];
    const ids = buildChannelReportList(reports, {
      view: generalReportView(),
      search: "FLAG",
    }).map((r) => r.id);
    expect(ids).toEqual(["flags"]);
  });

  it("priority filter keeps only the selected priorities", () => {
    const reports = [
      report({ id: "p0", priority: "P0" }),
      report({ id: "p2", priority: "P2" }),
      report({ id: "none", priority: null }),
    ];
    const ids = buildChannelReportList(reports, {
      view: generalReportView(),
      priorities: ["P0"],
    }).map((r) => r.id);
    expect(ids).toEqual(["p0"]);
  });

  it.each([
    ["needs-review", ["pr"]],
    ["ready", ["ready"]],
    ["running", ["queued", "live", "failed"]],
    ["all", ["pr", "ready", "queued", "live", "failed"]],
  ] as const)("status filter %s keeps %j", (status, expected) => {
    const reports = [
      report({ id: "pr", implementation_pr_url: "https://example.com/pr/1" }),
      report({ id: "ready" }),
      report({ id: "queued", status: "potential" }),
      report({ id: "live", status: "in_progress" }),
      report({ id: "failed", status: "failed" }),
    ];
    const ids = buildChannelReportList(reports, {
      view: generalReportView(),
      status,
    }).map((r) => r.id);
    expect(ids).toEqual(expected);
  });

  it("status counts bucket every non-archived report exactly once and ignore the status filter", () => {
    const reports = [
      report({ id: "pr", implementation_pr_url: "https://example.com/pr/1" }),
      report({ id: "ready" }),
      report({ id: "queued", status: "potential" }),
      report({ id: "failed", status: "failed" }),
      report({ id: "archived", status: "suppressed" }),
    ];
    const counts = countChannelReportsByStatus(reports, {
      view: generalReportView(),
    });
    expect(counts).toEqual({
      all: 4,
      "needs-review": 1,
      ready: 1,
      running: 2,
    });
  });

  it("countChannelReportsForMe counts suggested-reviewer reports in scope", () => {
    const reports = [
      report({ id: "a", channel_id: "s1", is_suggested_reviewer: true }),
      report({ id: "b", channel_id: "s1", is_suggested_reviewer: false }),
      report({ id: "c", channel_id: "s2", is_suggested_reviewer: true }),
      report({ id: "gone", status: "suppressed", is_suggested_reviewer: true }),
    ];
    expect(countChannelReportsForMe(reports, channelReportView("s1"))).toBe(1);
    expect(countChannelReportsForMe(reports, generalReportView())).toBe(2);
  });
});
