import type {
  SignalReport,
  SignalReportsQueryParams,
  SignalReportsResponse,
} from "@posthog/shared/types";
import type { InfiniteData, QueryClient } from "@tanstack/react-query";

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

export function seedInboxReportDetailCache(
  queryClient: QueryClient,
  report: SignalReport,
): void {
  queryClient.setQueryData(inboxReportDetailQueryKey(report.id), report);
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
