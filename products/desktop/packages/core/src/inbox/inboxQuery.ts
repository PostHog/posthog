import type {
  SignalReport,
  SignalReportsQueryParams,
  SignalReportsResponse,
} from "@posthog/shared/types";
import type {
  InfiniteData,
  QueryClient,
  QueryKey,
} from "@tanstack/react-query";

/**
 * React Query key factory for inbox-reports queries. Lives in its own
 * trpc-free leaf module so utils can share keys without pulling the
 * renderer trpc client into unit-test imports.
 */
export const inboxReportKeys = {
  all: ["inbox", "signal-reports"] as const,
  list: (params?: SignalReportsQueryParams) =>
    [...inboxReportKeys.all, "list", params ?? {}] as const,
  infiniteList: (params?: SignalReportsQueryParams) =>
    [...inboxReportKeys.all, "infinite-list", params ?? {}] as const,
  detail: (reportId: string) =>
    [...inboxReportKeys.all, reportId, "detail"] as const,
  artefacts: (reportId: string) =>
    [...inboxReportKeys.all, reportId, "artefacts"] as const,
  chartData: (reportId: string, chartId: string) =>
    [...inboxReportKeys.all, reportId, "chart-data", chartId] as const,
  signals: (reportId: string) =>
    [...inboxReportKeys.all, reportId, "signals"] as const,
  availableSuggestedReviewers: (authIdentity: string | null) =>
    [
      ...inboxReportKeys.all,
      authIdentity ?? "anonymous",
      "available-reviewers",
    ] as const,
  signalProcessingState: ["inbox", "signal-processing-state"] as const,
};

// Long enough for hover/focus intent to survive a pause before navigation,
// while keeping status-sensitive report data reasonably fresh.
export const INBOX_REPORT_DETAIL_STALE_TIME_MS = 10 * 60_000;

/** Shared keys for the per-team / per-user Self-driving config queries. */
export const signalsConfigKeys = {
  teamConfig: ["signals", "team-config"] as const,
  userAutonomyConfig: ["signals", "user-autonomy-config"] as const,
  sourceConfigs: ["signals", "source-configs"] as const,
};

export function inboxReportDetailQueryKey(reportId: string) {
  return inboxReportKeys.detail(reportId);
}

export function findReportInInboxListCache(
  queryClient: QueryClient,
  reportId: string,
): SignalReport | undefined {
  /**
   * `getQueriesData` matches by prefix, so every query under
   * `["inbox", "signal-reports", ...]` is returned – including detail entries
   * seeded as bare `SignalReport`s and scope-count entries holding a `number`.
   * Narrow each entry by shape before peeking at `pages` / `results`.
   */
  const entries = queryClient.getQueriesData<unknown>({
    queryKey: inboxReportKeys.all,
  });

  for (const [, data] of entries) {
    if (!data || typeof data !== "object") continue;

    if (
      "pages" in data &&
      Array.isArray((data as InfiniteData<unknown>).pages)
    ) {
      const pages = (data as InfiniteData<SignalReportsResponse>).pages;
      for (const page of pages) {
        if (!page || !Array.isArray(page.results)) continue;
        const found = page.results.find((report) => report.id === reportId);
        if (found) return found;
      }
      continue;
    }

    if (
      "results" in data &&
      Array.isArray((data as SignalReportsResponse).results)
    ) {
      const found = (data as SignalReportsResponse).results.find(
        (report) => report.id === reportId,
      );
      if (found) return found;
    }
  }

  return undefined;
}

export function resolveInboxReportDetailCache(
  queryClient: QueryClient,
  reportId: string,
): SignalReport | undefined {
  const seeded = queryClient.getQueryData<SignalReport>(
    inboxReportDetailQueryKey(reportId),
  );
  if (seeded) return seeded;
  return findReportInInboxListCache(queryClient, reportId);
}

export function resolveInboxReportForRender(
  report: SignalReport | null | undefined,
  cachedReport: SignalReport | null,
): SignalReport | null {
  return report === undefined ? cachedReport : report;
}

export type InboxReportCacheSnapshot = Array<readonly [QueryKey, unknown]>;

function queryAcceptsReportStatus(
  queryKey: QueryKey,
  status: SignalReport["status"],
): boolean {
  const params = queryKey[3];
  if (!params || typeof params !== "object" || !("status" in params)) {
    return true;
  }
  const statusFilter = (params as SignalReportsQueryParams).status;
  if (!statusFilter) return true;
  return statusFilter.split(",").some((value) => value.trim() === status);
}

function updateReportPage(
  page: SignalReportsResponse,
  reportsById: Map<string, SignalReport>,
  queryKey: QueryKey,
  removedCount: number,
): SignalReportsResponse {
  return {
    ...page,
    results: page.results.flatMap((report) => {
      const updated = reportsById.get(report.id);
      if (!updated) return [report];
      return queryAcceptsReportStatus(queryKey, updated.status)
        ? [updated]
        : [];
    }),
    count: Math.max(0, page.count - removedCount),
  };
}

/**
 * Apply report updates to cached detail and list queries before the server refresh finishes.
 * The snapshot lets a mutation restore the exact previous cache after a failed request.
 */
export function updateInboxReportCaches(
  queryClient: QueryClient,
  reports: SignalReport[],
): InboxReportCacheSnapshot {
  const reportsById = new Map(reports.map((report) => [report.id, report]));
  const snapshot: InboxReportCacheSnapshot = [];
  const entries = queryClient.getQueriesData<unknown>({
    queryKey: inboxReportKeys.all,
  });

  for (const [queryKey, data] of entries) {
    let updatedData: unknown = data;
    const kind = queryKey[2];

    if (
      typeof kind === "string" &&
      queryKey[3] === "detail" &&
      reportsById.has(kind) &&
      data
    ) {
      updatedData = reportsById.get(kind);
    } else if (
      kind === "list" &&
      data &&
      typeof data === "object" &&
      "results" in data &&
      Array.isArray((data as SignalReportsResponse).results)
    ) {
      const page = data as SignalReportsResponse;
      const removedCount = page.results.filter((report) => {
        const updated = reportsById.get(report.id);
        return updated && !queryAcceptsReportStatus(queryKey, updated.status);
      }).length;
      if (page.results.some((report) => reportsById.has(report.id))) {
        updatedData = updateReportPage(
          page,
          reportsById,
          queryKey,
          removedCount,
        );
      }
    } else if (
      kind === "infinite-list" &&
      data &&
      typeof data === "object" &&
      "pages" in data &&
      Array.isArray((data as InfiniteData<unknown>).pages)
    ) {
      const infiniteData = data as InfiniteData<SignalReportsResponse>;
      const cachedReportIds = new Set(
        infiniteData.pages.flatMap((page) =>
          page.results
            .filter((report) => reportsById.has(report.id))
            .map((report) => report.id),
        ),
      );
      if (cachedReportIds.size > 0) {
        const removedCount = [...cachedReportIds].filter((reportId) => {
          const updated = reportsById.get(reportId);
          return updated && !queryAcceptsReportStatus(queryKey, updated.status);
        }).length;
        updatedData = {
          ...infiniteData,
          pages: infiniteData.pages.map((page) =>
            updateReportPage(page, reportsById, queryKey, removedCount),
          ),
        };
      }
    }

    if (updatedData !== data) {
      snapshot.push([queryKey, data]);
      queryClient.setQueryData(queryKey, updatedData);
    }
  }

  return snapshot;
}

export function restoreInboxReportCaches(
  queryClient: QueryClient,
  snapshot: InboxReportCacheSnapshot,
): void {
  for (const [queryKey, data] of snapshot) {
    queryClient.setQueryData(queryKey, data);
  }
}
