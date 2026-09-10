import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import { groupReportsByAge } from "./reportAgeGroups";

const DAY = 24 * 60 * 60 * 1000;

function report(id: string, daysAgo: number): SignalReport {
  const createdAt = new Date(Date.now() - daysAgo * DAY).toISOString();
  return {
    id,
    title: id,
    summary: null,
    status: "ready",
    total_weight: 0,
    signal_count: 0,
    created_at: createdAt,
    updated_at: createdAt,
    artefact_count: 0,
  };
}

describe("groupReportsByAge", () => {
  it("widens the buckets with age instead of naming every day", () => {
    expect(
      groupReportsByAge([
        report("now", 0),
        report("earlier-today", 0),
        report("yesterday", 1),
        report("this-week", 3),
        report("this-month", 12),
        report("older", 90),
      ]).map((group) => [group.label, ...group.reports.map((r) => r.id)]),
    ).toEqual([
      ["Today", "now", "earlier-today"],
      ["Yesterday", "yesterday"],
      ["This week", "this-week"],
      ["This month", "this-month"],
      ["Earlier", "older"],
    ]);
  });

  it("keeps the list's own order inside each bucket, newest bucket first", () => {
    expect(
      groupReportsByAge([
        report("p0-this-month", 12),
        report("p1-today", 0),
        report("p2-this-month", 14),
      ]).map((group) => [group.label, ...group.reports.map((r) => r.id)]),
    ).toEqual([
      ["Today", "p1-today"],
      ["This month", "p0-this-month", "p2-this-month"],
    ]);
  });

  it("runs the buckets oldest first when the list is sorted that way", () => {
    expect(
      groupReportsByAge(
        [report("today", 0), report("yesterday", 1), report("older", 90)],
        { oldestFirst: true },
      ).map((group) => group.label),
    ).toEqual(["Earlier", "Yesterday", "Today"]);
  });
});
