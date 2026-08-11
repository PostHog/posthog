import type { SignalReport } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  buildBulkActionEvents,
  buildDetailActionEvent,
  snapshotReportList,
} from "./reportActionEvents";

function fakeReport(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "r1",
    title: "Report one",
    summary: null,
    status: "ready",
    total_weight: 0,
    signal_count: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    artefact_count: 0,
    priority: "P1",
    actionability: "immediately_actionable",
    ...overrides,
  } as SignalReport;
}

describe("snapshotReportList", () => {
  it("captures rank, title, and list size per report", () => {
    const snapshot = snapshotReportList([
      fakeReport({ id: "a", title: "A" }),
      fakeReport({ id: "b", title: "B" }),
    ]);
    expect(snapshot.listSize).toBe(2);
    expect(snapshot.byId.get("b")).toMatchObject({ rank: 1, title: "B" });
  });
});

describe("buildBulkActionEvents", () => {
  it("derives one toolbar event per target with bulk flags", () => {
    const snapshot = snapshotReportList([
      fakeReport({ id: "a", priority: "P0" }),
      fakeReport({ id: "b", priority: "P2" }),
    ]);
    const events = buildBulkActionEvents("delete", ["a", "b"], snapshot);
    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({
      report_id: "a",
      action_type: "delete",
      surface: "toolbar",
      is_bulk: true,
      bulk_size: 2,
      rank: 0,
      list_size: 2,
      priority: "P0",
    });
  });

  it("marks a single target as non-bulk and falls back for unknown ids", () => {
    const snapshot = snapshotReportList([fakeReport({ id: "a" })]);
    const events = buildBulkActionEvents("snooze", ["gone"], snapshot);
    expect(events[0]).toMatchObject({
      is_bulk: false,
      bulk_size: 1,
      rank: -1,
      report_title: null,
      priority: null,
    });
  });
});

describe("buildDetailActionEvent", () => {
  it("fills detail-pane boilerplate and merges extras", () => {
    const event = buildDetailActionEvent(
      fakeReport({ id: "x", title: "X" }),
      "expand_why",
      { why_field: "priority" },
    );
    expect(event).toMatchObject({
      report_id: "x",
      report_title: "X",
      action_type: "expand_why",
      surface: "detail_pane",
      is_bulk: false,
      bulk_size: 1,
      why_field: "priority",
    });
  });
});
