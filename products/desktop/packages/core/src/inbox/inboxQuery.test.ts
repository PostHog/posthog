import type { SignalReport } from "@posthog/shared/types";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import {
  findReportInInboxListCache,
  inboxReportDetailQueryKey,
  resolveInboxReportDetailCache,
  resolveInboxReportForRender,
  restoreInboxReportCaches,
  updateInboxReportCaches,
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

  it("resolves a populated detail cache", () => {
    const queryClient = new QueryClient();
    const report = fakeReport("r-7");

    queryClient.setQueryData(inboxReportDetailQueryKey("r-7"), report);

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

    queryClient.setQueryData(
      inboxReportDetailQueryKey(seededDetail.id),
      seededDetail,
    );
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

  it("does not fall back after an authoritative missing response", () => {
    const cachedReport = fakeReport("stale");

    expect(resolveInboxReportForRender(undefined, cachedReport)).toEqual(
      cachedReport,
    );
    expect(resolveInboxReportForRender(null, cachedReport)).toBeNull();
  });

  it("updates cached report states and restores them after a failed request", () => {
    const queryClient = new QueryClient();
    const report = fakeReport("changing");
    const other = fakeReport("other");
    const readyListKey = [
      "inbox",
      "signal-reports",
      "list",
      { status: "ready" },
    ] as const;
    const archiveListKey = [
      "inbox",
      "signal-reports",
      "infinite-list",
      { status: "ready,resolved" },
    ] as const;
    const readyCountKey = [
      "inbox",
      "signal-reports",
      "list",
      { status: "ready", count_only: true },
    ] as const;
    const resolvedCountKey = [
      "inbox",
      "signal-reports",
      "list",
      { status: "resolved", count_only: true },
    ] as const;
    const readyList = { results: [report, other], count: 2 };
    const archiveList = {
      pages: [
        { results: [report], count: 2 },
        { results: [other], count: 2 },
      ],
      pageParams: [0, 1],
    };

    queryClient.setQueryData(inboxReportDetailQueryKey(report.id), report);
    queryClient.setQueryData(readyListKey, readyList);
    queryClient.setQueryData(archiveListKey, archiveList);
    queryClient.setQueryData(readyCountKey, { results: [], count: 2 });
    queryClient.setQueryData(resolvedCountKey, { results: [], count: 4 });
    queryClient.setQueryData(
      ["inbox", "signal-reports", "scope-count", "for-you"],
      42,
    );

    const resolved = { ...report, status: "resolved" as const };
    const snapshot = updateInboxReportCaches(queryClient, [resolved]);

    expect(
      queryClient.getQueryData<SignalReport>(
        inboxReportDetailQueryKey(report.id),
      ),
    ).toEqual(resolved);
    expect(queryClient.getQueryData(readyListKey)).toEqual({
      results: [other],
      count: 1,
    });
    expect(queryClient.getQueryData(archiveListKey)).toEqual({
      pages: [
        { results: [resolved], count: 2 },
        { results: [other], count: 2 },
      ],
      pageParams: [0, 1],
    });
    expect(queryClient.getQueryData(readyCountKey)).toEqual({
      results: [],
      count: 1,
    });
    expect(queryClient.getQueryData(resolvedCountKey)).toEqual({
      results: [],
      count: 5,
    });
    expect(
      queryClient.getQueryData([
        "inbox",
        "signal-reports",
        "scope-count",
        "for-you",
      ]),
    ).toBe(42);

    restoreInboxReportCaches(queryClient, snapshot);

    expect(
      queryClient.getQueryData(inboxReportDetailQueryKey(report.id)),
    ).toEqual(report);
    expect(queryClient.getQueryData(readyListKey)).toEqual(readyList);
    expect(queryClient.getQueryData(archiveListKey)).toEqual(archiveList);
    expect(queryClient.getQueryData(readyCountKey)).toEqual({
      results: [],
      count: 2,
    });
    expect(queryClient.getQueryData(resolvedCountKey)).toEqual({
      results: [],
      count: 4,
    });
  });

  it("restores one failed report without overwriting another report update", () => {
    const queryClient = new QueryClient();
    const first = fakeReport("first");
    const second = fakeReport("second");
    const listKey = [
      "inbox",
      "signal-reports",
      "list",
      { status: "ready" },
    ] as const;

    queryClient.setQueryData(listKey, {
      results: [first, second],
      count: 2,
    });
    queryClient.setQueryData(inboxReportDetailQueryKey(first.id), first);
    queryClient.setQueryData(inboxReportDetailQueryKey(second.id), second);

    const firstResolved = { ...first, status: "resolved" as const };
    const secondResolved = { ...second, status: "resolved" as const };
    const firstSnapshot = updateInboxReportCaches(
      queryClient,
      [firstResolved],
      [first],
    );
    updateInboxReportCaches(queryClient, [secondResolved], [second]);

    restoreInboxReportCaches(queryClient, firstSnapshot);

    expect(queryClient.getQueryData(listKey)).toEqual({
      results: [first],
      count: 1,
    });
    expect(
      queryClient.getQueryData(inboxReportDetailQueryKey(first.id)),
    ).toEqual(first);
    expect(
      queryClient.getQueryData(inboxReportDetailQueryKey(second.id)),
    ).toEqual(secondResolved);
  });
});
