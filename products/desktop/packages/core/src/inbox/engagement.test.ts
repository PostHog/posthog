import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  buildBulkActionEvents,
  buildInboxViewedProperties,
  type InboxDetailTab,
  inboxDetailTabReports,
} from "./engagement";

function fakeReport(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "r1",
    title: "Test report",
    summary: "Summary",
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-06-05T00:00:00Z",
    updated_at: "2026-06-05T00:00:00Z",
    artefact_count: 0,
    priority: null,
    actionability: null,
    is_suggested_reviewer: false,
    source_products: [],
    implementation_pr_url: null,
    ...overrides,
  };
}

const NO_FILTERS = {
  sourceProductFilter: [],
  priorityFilter: [],
  searchQuery: "",
  isDefaultScope: true,
};

describe("buildBulkActionEvents", () => {
  it("marks single-report actions as non-bulk", () => {
    const [event, ...rest] = buildBulkActionEvents({
      reports: [fakeReport({ id: "a", priority: "P1" })],
      actionType: "snooze",
      surface: "detail_pane",
    });

    expect(rest).toHaveLength(0);
    expect(event).toMatchObject({
      report_id: "a",
      action_type: "snooze",
      surface: "detail_pane",
      is_bulk: false,
      bulk_size: 1,
      priority: "P1",
    });
  });

  it("emits one bulk-flagged event per report", () => {
    const events = buildBulkActionEvents({
      reports: [fakeReport({ id: "a" }), fakeReport({ id: "b" })],
      actionType: "delete",
      surface: "toolbar",
    });

    expect(events.map((e) => e.report_id)).toEqual(["a", "b"]);
    expect(events.every((e) => e.is_bulk && e.bulk_size === 2)).toBe(true);
    expect(events.every((e) => e.action_type === "delete")).toBe(true);
  });

  it("attaches dismissal reason/note only for dismiss, truncating the note", () => {
    const longNote = "x".repeat(600);
    const [dismissed] = buildBulkActionEvents({
      reports: [fakeReport({ id: "a" })],
      actionType: "dismiss",
      surface: "toolbar",
      dismissal: { reason: "not_relevant", note: longNote },
    });
    expect(dismissed.dismissal_reason).toBe("not_relevant");
    expect(dismissed.dismissal_note).toHaveLength(500);

    const [snoozed] = buildBulkActionEvents({
      reports: [fakeReport({ id: "a" })],
      actionType: "snooze",
      surface: "toolbar",
      dismissal: { reason: "not_relevant", note: longNote },
    });
    expect(snoozed.dismissal_reason).toBeUndefined();
    expect(snoozed.dismissal_note).toBeUndefined();
  });
});

describe("buildInboxViewedProperties", () => {
  it("counts visible reports, tab badges, and total", () => {
    const props = buildInboxViewedProperties({
      visibleReports: [fakeReport({ id: "a" }), fakeReport({ id: "b" })],
      totalCount: 65,
      tabCounts: { pulls: 38, reports: 62 },
      filters: NO_FILTERS,
    });

    expect(props.report_count).toBe(2);
    expect(props.total_count).toBe(65);
    expect(props.ready_count).toBe(2);
    expect(props.pulls_count).toBe(38);
    expect(props.reports_count).toBe(62);
    expect(props.is_empty).toBe(false);
    expect(props.status_filter_count).toBe(0);
  });

  it("breaks visible reports down by priority and actionability", () => {
    const props = buildInboxViewedProperties({
      visibleReports: [
        fakeReport({ priority: "P0", actionability: "immediately_actionable" }),
        fakeReport({ priority: "P0", actionability: "requires_human_input" }),
        fakeReport({ priority: "P2", actionability: "not_actionable" }),
        fakeReport({ priority: null, actionability: null }),
      ],
      totalCount: 4,
      tabCounts: { pulls: 0, reports: 4 },
      filters: NO_FILTERS,
    });

    expect(props.priority_p0_count).toBe(2);
    expect(props.priority_p2_count).toBe(1);
    expect(props.priority_unknown_count).toBe(1);
    expect(props.actionability_immediately_actionable_count).toBe(1);
    expect(props.actionability_requires_human_input_count).toBe(1);
    expect(props.actionability_not_actionable_count).toBe(1);
    expect(props.actionability_unknown_count).toBe(1);
  });

  it("only counts ready reports toward ready_count", () => {
    const props = buildInboxViewedProperties({
      visibleReports: [
        fakeReport({ status: "ready" }),
        fakeReport({ status: "in_progress" }),
      ],
      totalCount: 2,
      tabCounts: { pulls: 0, reports: 1 },
      filters: NO_FILTERS,
    });

    expect(props.ready_count).toBe(1);
  });

  it("reports is_empty when the total count is zero", () => {
    const props = buildInboxViewedProperties({
      visibleReports: [],
      totalCount: 0,
      tabCounts: { pulls: 0, reports: 0 },
      filters: NO_FILTERS,
    });

    expect(props.is_empty).toBe(true);
    expect(props.has_active_filters).toBe(false);
  });

  it.each([
    ["source product", { sourceProductFilter: ["error_tracking"] }],
    ["priority", { priorityFilter: ["P0"] }],
    ["search", { searchQuery: "  crash  " }],
    ["non-default scope", { isDefaultScope: false }],
  ])("flags has_active_filters for a %s filter", (_label, partial) => {
    const props = buildInboxViewedProperties({
      visibleReports: [fakeReport()],
      totalCount: 1,
      tabCounts: { pulls: 0, reports: 1 },
      filters: { ...NO_FILTERS, ...partial },
    });

    expect(props.has_active_filters).toBe(true);
  });

  it("does not flag has_active_filters for a whitespace-only search", () => {
    const props = buildInboxViewedProperties({
      visibleReports: [fakeReport()],
      totalCount: 1,
      tabCounts: { pulls: 0, reports: 1 },
      filters: { ...NO_FILTERS, searchQuery: "   " },
    });

    expect(props.has_active_filters).toBe(false);
  });
});

describe("inboxDetailTabReports", () => {
  const pull = fakeReport({
    id: "pr",
    status: "ready",
    implementation_pr_url: "https://github.com/x/y/pull/1",
  });
  const reportRow = fakeReport({ id: "rep", status: "ready" });
  const queuedRun = fakeReport({ id: "queued", status: "candidate" });
  const liveRun = fakeReport({ id: "live", status: "in_progress" });
  const failedRun = fakeReport({ id: "failed", status: "failed" });

  const cases: Array<[InboxDetailTab, SignalReport[], SignalReport[]]> = [
    ["pulls", [pull, queuedRun, reportRow], [pull]],
    ["reports", [reportRow, pull, queuedRun, failedRun], [reportRow]],
    ["runs", [queuedRun, liveRun, failedRun], [queuedRun, liveRun, failedRun]],
  ];
  it.each(cases)(
    "keeps the rows the %s tab renders",
    (tab, input, expected) => {
      expect(inboxDetailTabReports(tab, input)).toEqual(expected);
    },
  );

  it("treats a ready non-run report as a finished run on the runs tab", () => {
    // `ready` is shared by isReportTabReport and isFinishedRunReport, so a ready
    // report renders in both the Reports tab and the Runs tab's "Recently
    // finished" section. The runs list reflects that overlap.
    expect(inboxDetailTabReports("runs", [queuedRun, reportRow])).toEqual([
      queuedRun,
      reportRow,
    ]);
  });

  it("orders runs Queued → Live → Finished, newest-first within a section", () => {
    const olderFinished = fakeReport({
      id: "fin-old",
      status: "ready",
      updated_at: "2026-06-01T00:00:00Z",
    });
    const newerFinished = fakeReport({
      id: "fin-new",
      status: "failed",
      updated_at: "2026-06-09T00:00:00Z",
    });
    // Deliberately shuffled input; output must follow the rendered order.
    const visible = inboxDetailTabReports("runs", [
      olderFinished,
      liveRun,
      newerFinished,
      queuedRun,
    ]);
    expect(visible.map((r) => r.id)).toEqual([
      "queued",
      "live",
      "fin-new",
      "fin-old",
    ]);
  });

  it("ranks a recently-finished run against the runs list (not rank -1)", () => {
    // The regression: `failed`/`ready` runs render in the Runs tab's "Recently
    // finished" section but aren't `isAgentRunReport`, so they used to fall out
    // of the tracked list and report rank -1.
    const visible = inboxDetailTabReports("runs", [
      queuedRun,
      liveRun,
      failedRun,
    ]);
    expect(visible.findIndex((r) => r.id === failedRun.id)).toBe(2);
  });
});
