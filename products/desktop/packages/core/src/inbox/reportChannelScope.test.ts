import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import {
  buildChannelReportList,
  channelReportView,
  countChannelReportsByStatus,
  generalReportView,
  NEEDS_ATTENTION_LIMIT,
  splitChannelReportSections,
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

  it("archived bucket keeps only suppressed and resolved reports", () => {
    const reports = [
      report({ id: "ready" }),
      report({ id: "suppressed", status: "suppressed" }),
      report({ id: "resolved", status: "resolved" }),
      report({ id: "deleted", status: "deleted" }),
    ];
    const ids = buildChannelReportList(reports, {
      view: generalReportView(),
      status: "archived",
    }).map((r) => r.id);
    expect(ids).toEqual(["suppressed", "resolved"]);
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
      archived: 0,
    });
  });
});

describe("splitChannelReportSections", () => {
  it("pins prioritized actionable reports P0-first, caps the pin, and keeps overflow in the stream", () => {
    const ordered = [
      report({
        id: "new-p3",
        priority: "P3",
        updated_at: "2026-06-09T00:00:00Z",
      }),
      report({
        id: "p1-new",
        priority: "P1",
        updated_at: "2026-06-08T00:00:00Z",
      }),
      report({
        id: "p2-a",
        priority: "P2",
        updated_at: "2026-06-07T00:00:00Z",
      }),
      report({ id: "p0", priority: "P0", updated_at: "2026-06-06T00:00:00Z" }),
      report({
        id: "p1-old",
        priority: "P1",
        updated_at: "2026-06-05T00:00:00Z",
      }),
      report({
        id: "p2-b",
        priority: "P2",
        updated_at: "2026-06-04T00:00:00Z",
      }),
    ];
    const { needsAttention, rest } = splitChannelReportSections(ordered);
    expect(needsAttention.map((r) => r.id)).toEqual([
      "p0",
      "p1-new",
      "p1-old",
      "p2-a",
      "p2-b",
    ]);
    expect(needsAttention).toHaveLength(NEEDS_ATTENTION_LIMIT);
    // The P3 overflowed the cap and stays in its chronological slot.
    expect(rest.map((r) => r.id)).toEqual(["new-p3"]);
  });

  it("never pins reports the agent is still working, nor unprioritized ones", () => {
    const ordered = [
      report({ id: "running-p0", status: "in_progress", priority: "P0" }),
      report({ id: "queued-p0", status: "candidate", priority: "P0" }),
      report({ id: "no-priority", status: "ready", priority: undefined }),
      report({ id: "failed-p2", status: "failed", priority: "P2" }),
      report({
        id: "pr-p1",
        status: "in_progress",
        priority: "P1",
        implementation_pr_url: "https://gh/pr/1",
      }),
    ];
    const { needsAttention, rest } = splitChannelReportSections(ordered);
    // A PR to review pins even mid-run; a bare run and a priority-less ready report do not.
    expect(needsAttention.map((r) => r.id)).toEqual(["pr-p1", "failed-p2"]);
    expect(rest.map((r) => r.id)).toEqual([
      "running-p0",
      "queued-p0",
      "no-priority",
    ]);
  });
});
