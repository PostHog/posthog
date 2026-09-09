import type {
  SignalReport,
  SignalReportsQueryParams,
  SignalReportsResponse,
} from "@posthog/shared/types";
import type {
  InfiniteData,
  Query,
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

interface PositionedReport {
  report: SignalReport;
  index: number;
}

interface PositionedInfiniteReport extends PositionedReport {
  pageIndex: number;
}

export type InboxReportCacheSnapshot = Array<
  | {
      kind: "detail";
      queryKey: QueryKey;
      query: Query;
      report: SignalReport;
    }
  | {
      kind: "list";
      queryKey: QueryKey;
      query: Query;
      reports: PositionedReport[];
      countDelta: number;
    }
  | {
      kind: "infinite-list";
      queryKey: QueryKey;
      query: Query;
      reports: PositionedInfiniteReport[];
      countDelta: number;
    }
>;

function queryParams(queryKey: QueryKey): SignalReportsQueryParams {
  const params = queryKey[3];
  return params && typeof params === "object"
    ? (params as SignalReportsQueryParams)
    : {};
}

function commaSeparatedValueIncludes(
  filter: string | undefined,
  value: string | null | undefined,
): boolean {
  if (!filter) return true;
  if (!value) return false;
  return filter.split(",").some((item) => item.trim() === value);
}

function queryAcceptsReport(
  queryKey: QueryKey,
  report: SignalReport,
  reviewerMembership: Map<string, Set<string>>,
): boolean {
  const params = queryParams(queryKey);
  if (!commaSeparatedValueIncludes(params.status, report.status)) return false;
  if (!commaSeparatedValueIncludes(params.priority, report.priority)) {
    return false;
  }
  if (
    !commaSeparatedValueIncludes(params.actionability, report.actionability)
  ) {
    return false;
  }
  if (
    params.source_product &&
    !report.source_products?.some((source) =>
      commaSeparatedValueIncludes(params.source_product, source),
    )
  ) {
    return false;
  }
  if (
    params.has_implementation_pr !== undefined &&
    params.has_implementation_pr !== Boolean(report.implementation_pr_url)
  ) {
    return false;
  }
  if (params.channel_id && params.channel_id !== report.channel_id) {
    return false;
  }
  if (
    params.suggested_reviewers &&
    !reviewerMembership.get(report.id)?.has(params.suggested_reviewers.trim())
  ) {
    return false;
  }
  return true;
}

function cachedReports(data: unknown): SignalReport[] {
  if (!data || typeof data !== "object") return [];
  if ("pages" in data && Array.isArray((data as InfiniteData<unknown>).pages)) {
    return (data as InfiniteData<SignalReportsResponse>).pages.flatMap(
      (page) => page.results,
    );
  }
  if (
    "results" in data &&
    Array.isArray((data as SignalReportsResponse).results)
  ) {
    return (data as SignalReportsResponse).results;
  }
  return [];
}

function buildReviewerMembership(
  entries: Array<[QueryKey, unknown]>,
  reportsById: Map<string, SignalReport>,
): Map<string, Set<string>> {
  const membership = new Map<string, Set<string>>();
  for (const [queryKey, data] of entries) {
    const reviewerScope = queryParams(queryKey).suggested_reviewers?.trim();
    if (!reviewerScope) continue;
    for (const report of cachedReports(data)) {
      if (!reportsById.has(report.id)) continue;
      const scopes = membership.get(report.id) ?? new Set<string>();
      scopes.add(reviewerScope);
      membership.set(report.id, scopes);
    }
  }
  return membership;
}

function reportCountDelta(
  queryKey: QueryKey,
  reportsById: Map<string, SignalReport>,
  previousReportsById: Map<string, SignalReport>,
  reviewerMembership: Map<string, Set<string>>,
): number {
  let delta = 0;
  for (const [reportId, updatedReport] of reportsById) {
    const previousReport = previousReportsById.get(reportId);
    if (!previousReport) continue;
    delta += Number(
      queryAcceptsReport(queryKey, updatedReport, reviewerMembership),
    );
    delta -= Number(
      queryAcceptsReport(queryKey, previousReport, reviewerMembership),
    );
  }
  return delta;
}

function updateReportPage(
  page: SignalReportsResponse,
  reportsById: Map<string, SignalReport>,
  queryKey: QueryKey,
  countDelta: number,
  reviewerMembership: Map<string, Set<string>>,
): SignalReportsResponse {
  return {
    ...page,
    results: page.results.flatMap((report) => {
      const updated = reportsById.get(report.id);
      if (!updated) return [report];
      return queryAcceptsReport(queryKey, updated, reviewerMembership)
        ? [updated]
        : [];
    }),
    count: Math.max(0, page.count + countDelta),
  };
}

function positionedReports(
  page: SignalReportsResponse,
  reportsById: Map<string, SignalReport>,
): PositionedReport[] {
  return page.results.flatMap((report, index) =>
    reportsById.has(report.id) ? [{ report, index }] : [],
  );
}

function restoreReportPage(
  page: SignalReportsResponse,
  reports: PositionedReport[],
  countDelta: number,
): SignalReportsResponse {
  const restoredIds = new Set(reports.map(({ report }) => report.id));
  const results = page.results.filter((report) => !restoredIds.has(report.id));
  for (const { report, index } of reports) {
    results.splice(Math.min(index, results.length), 0, report);
  }
  return {
    ...page,
    results,
    count: Math.max(0, page.count - countDelta),
  };
}

/**
 * Apply report updates to cached detail and list queries before the server refresh finishes.
 * The snapshot restores only the failed reports so concurrent updates stay in the cache.
 */
export function updateInboxReportCaches(
  queryClient: QueryClient,
  reports: SignalReport[],
  previousReports: SignalReport[] = reports.flatMap((report) => {
    const previous = resolveInboxReportDetailCache(queryClient, report.id);
    return previous ? [previous] : [];
  }),
): InboxReportCacheSnapshot {
  const reportsById = new Map(reports.map((report) => [report.id, report]));
  const previousReportsById = new Map(
    previousReports.map((report) => [report.id, report]),
  );
  const snapshot: InboxReportCacheSnapshot = [];
  const entries = queryClient.getQueriesData<unknown>({
    queryKey: inboxReportKeys.all,
  });
  const reviewerMembership = buildReviewerMembership(entries, reportsById);

  for (const [queryKey, data] of entries) {
    const query = queryClient.getQueryCache().find({ queryKey, exact: true });
    if (!query) continue;
    let updatedData: unknown = data;
    const kind = queryKey[2];

    if (
      typeof kind === "string" &&
      queryKey[3] === "detail" &&
      reportsById.has(kind) &&
      data
    ) {
      updatedData = reportsById.get(kind);
      snapshot.push({
        kind: "detail",
        queryKey,
        query,
        report: data as SignalReport,
      });
    } else if (
      kind === "list" &&
      data &&
      typeof data === "object" &&
      "results" in data &&
      Array.isArray((data as SignalReportsResponse).results)
    ) {
      const page = data as SignalReportsResponse;
      const reportsBeforeUpdate = positionedReports(page, reportsById);
      const countDelta = reportCountDelta(
        queryKey,
        reportsById,
        previousReportsById,
        reviewerMembership,
      );
      if (reportsBeforeUpdate.length > 0 || countDelta !== 0) {
        updatedData = updateReportPage(
          page,
          reportsById,
          queryKey,
          countDelta,
          reviewerMembership,
        );
        snapshot.push({
          kind: "list",
          queryKey,
          query,
          reports: reportsBeforeUpdate,
          countDelta,
        });
      }
    } else if (
      kind === "infinite-list" &&
      data &&
      typeof data === "object" &&
      "pages" in data &&
      Array.isArray((data as InfiniteData<unknown>).pages)
    ) {
      const infiniteData = data as InfiniteData<SignalReportsResponse>;
      const reportsBeforeUpdate = infiniteData.pages.flatMap(
        (page, pageIndex) =>
          positionedReports(page, reportsById).map((report) => ({
            ...report,
            pageIndex,
          })),
      );
      const countDelta = reportCountDelta(
        queryKey,
        reportsById,
        previousReportsById,
        reviewerMembership,
      );
      if (reportsBeforeUpdate.length > 0 || countDelta !== 0) {
        updatedData = {
          ...infiniteData,
          pages: infiniteData.pages.map((page) =>
            updateReportPage(
              page,
              reportsById,
              queryKey,
              countDelta,
              reviewerMembership,
            ),
          ),
        };
        snapshot.push({
          kind: "infinite-list",
          queryKey,
          query,
          reports: reportsBeforeUpdate,
          countDelta,
        });
      }
    }

    if (updatedData !== data) {
      queryClient.setQueryData(queryKey, updatedData);
    }
  }

  return snapshot;
}

export function restoreInboxReportCaches(
  queryClient: QueryClient,
  snapshot: InboxReportCacheSnapshot,
): void {
  for (const entry of snapshot) {
    const currentQuery = queryClient
      .getQueryCache()
      .find({ queryKey: entry.queryKey, exact: true });
    if (currentQuery !== entry.query) continue;
    if (entry.kind === "detail") {
      queryClient.setQueryData(entry.queryKey, entry.report);
      continue;
    }
    if (entry.kind === "list") {
      queryClient.setQueryData<SignalReportsResponse>(
        entry.queryKey,
        (current) =>
          current
            ? restoreReportPage(current, entry.reports, entry.countDelta)
            : current,
      );
      continue;
    }
    queryClient.setQueryData<InfiniteData<SignalReportsResponse>>(
      entry.queryKey,
      (current) =>
        current
          ? {
              ...current,
              pages: current.pages.map((page, pageIndex) =>
                restoreReportPage(
                  page,
                  entry.reports.filter(
                    (report) => report.pageIndex === pageIndex,
                  ),
                  entry.countDelta,
                ),
              ),
            }
          : current,
    );
  }
}
