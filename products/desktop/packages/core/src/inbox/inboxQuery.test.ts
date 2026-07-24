import type { SignalReport } from "@posthog/shared/types";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import {
  findReportInInboxListCache,
  inboxReportDetailQueryKey,
  resolveInboxReportDetailCache,
  seedInboxReportDetailCache,
} from "./inboxQuery";

function fakeReport(id: string): SignalReport {
  return {
    id,
    title: `Report ${id}`,
    summary: "Summary",
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    artefact_count: 0,
    priority: "P2",
    actionability: "immediately_actionable",
    is_suggested_reviewer: false,
    source_products: [],
    implementation_pr_url: null,
  };
}

describe("inboxQuery", () => {
  it("finds a report in an infinite list cache", () => {
    const queryClient = new QueryClient();
    const report = fakeReport("r-42");

    queryClient.setQueryData(
      ["inbox", "signal-reports", "infinite-list", { status: "ready" }],
      {
        pages: [{ results: [report], count: 1 }],
        pageParams: [0],
      },
    );

    expect(findReportInInboxListCache(queryClient, "r-42")).toEqual(report);
  });

  it("seeds and resolves the detail cache", () => {
    const queryClient = new QueryClient();
    const report = fakeReport("r-7");

    seedInboxReportDetailCache(queryClient, report);

    expect(queryClient.getQueryData(inboxReportDetailQueryKey("r-7"))).toEqual(
      report,
    );
    expect(resolveInboxReportDetailCache(queryClient, "r-7")).toEqual(report);
  });

  it("returns undefined when the report is not cached", () => {
    const queryClient = new QueryClient();
    expect(
      resolveInboxReportDetailCache(queryClient, "missing"),
    ).toBeUndefined();
  });

  it("ignores unrelated cache shapes under the shared key prefix", () => {
    const queryClient = new QueryClient();
    const seededDetail = fakeReport("seeded-detail");
    const listReport = fakeReport("in-list");

    seedInboxReportDetailCache(queryClient, seededDetail);
    queryClient.setQueryData(
      ["inbox", "signal-reports", "scope-count", "for-you"],
      42,
    );
    queryClient.setQueryData(
      ["inbox", "signal-reports", "list", { status: "ready" }],
      { results: [listReport], count: 1 },
    );

    expect(findReportInInboxListCache(queryClient, "in-list")).toEqual(
      listReport,
    );
    expect(findReportInInboxListCache(queryClient, "missing")).toBeUndefined();
  });
});
