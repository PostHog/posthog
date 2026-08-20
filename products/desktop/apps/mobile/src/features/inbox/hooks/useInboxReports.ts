import {
  buildArchiveListOrdering,
  buildPriorityFilterParam,
  buildSignalReportListOrdering,
  buildStatusFilterParam,
  buildSuggestedReviewerFilterParam,
  INBOX_DISMISSED_STATUS_FILTER,
  INBOX_REFETCH_INTERVAL_MS,
} from "@posthog/core/inbox/reportFiltering";
import { isRestorableReport } from "@posthog/core/inbox/reportMembership";
import type { DismissalReasonOptionValue } from "@posthog/shared";
import type {
  AvailableSuggestedReviewersResponse,
  CommitDiffResponse,
  SignalProcessingStateResponse,
  SignalReport,
  SignalReportArtefactsResponse,
  SignalReportRefundReason,
  SignalReportSignalsResponse,
  SignalReportsQueryParams,
  SignalReportsResponse,
  SuggestedReviewer,
  SuggestedReviewersArtefact,
  SuggestedReviewerWriteEntry,
} from "@posthog/shared/domain-types";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useMemo } from "react";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { useInboxFilterStore } from "../stores/inboxFilterStore";

export const inboxKeys = {
  all: ["inbox", "signal-reports"] as const,
  list: (params?: SignalReportsQueryParams) =>
    [...inboxKeys.all, "list", params ?? {}] as const,
  archived: (params?: SignalReportsQueryParams) =>
    [...inboxKeys.all, "archived", params ?? {}] as const,
  detail: (reportId: string) => [...inboxKeys.all, reportId, "detail"] as const,
  artefacts: (reportId: string) =>
    [...inboxKeys.all, reportId, "artefacts"] as const,
  signals: (reportId: string) =>
    [...inboxKeys.all, reportId, "signals"] as const,
  commitDiff: (reportId: string, artefactId: string) =>
    [...inboxKeys.all, reportId, "artefacts", artefactId, "diff"] as const,
  processingState: ["inbox", "signal-processing-state"] as const,
};

const REPORTS_PAGE_SIZE = 100;

export function getReportsNextPageParam(
  lastPage: SignalReportsResponse,
  allPages: SignalReportsResponse[],
): number | undefined {
  const loaded = allPages.reduce((n, page) => n + page.results.length, 0);
  return loaded < lastPage.count ? loaded : undefined;
}

export function useInboxReports(options?: { enabled?: boolean }) {
  const { projectId, oauthAccessToken } = useAuthStore();
  const sortField = useInboxFilterStore((s) => s.sortField);
  const sortDirection = useInboxFilterStore((s) => s.sortDirection);
  const statusFilter = useInboxFilterStore((s) => s.statusFilter);
  const sourceProductFilter = useInboxFilterStore((s) => s.sourceProductFilter);
  const suggestedReviewerFilter = useInboxFilterStore(
    (s) => s.suggestedReviewerFilter,
  );
  const priorityFilter = useInboxFilterStore((s) => s.priorityFilter);

  const params: SignalReportsQueryParams = {
    status: buildStatusFilterParam(statusFilter),
    ordering: buildSignalReportListOrdering(sortField, sortDirection),
    source_product:
      sourceProductFilter.length > 0
        ? sourceProductFilter.join(",")
        : undefined,
    suggested_reviewers:
      suggestedReviewerFilter.length > 0
        ? buildSuggestedReviewerFilterParam(suggestedReviewerFilter)
        : undefined,
    priority: buildPriorityFilterParam(priorityFilter),
  };

  const query = useInfiniteQuery({
    queryKey: inboxKeys.list(params),
    queryFn: ({ pageParam }) =>
      getPostHogApiClient().getSignalReports({
        ...params,
        limit: REPORTS_PAGE_SIZE,
        offset: pageParam,
      }),
    enabled: !!projectId && !!oauthAccessToken && (options?.enabled ?? true),
    refetchInterval: INBOX_REFETCH_INTERVAL_MS,
    initialPageParam: 0,
    getNextPageParam: getReportsNextPageParam,
  });

  const reports = useMemo(
    () => query.data?.pages.flatMap((page) => page.results) ?? [],
    [query.data?.pages],
  );

  return {
    reports,
    totalCount: query.data?.pages[0]?.count ?? 0,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error?.message ?? null,
    refetch: query.refetch,
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    fetchNextPage: () => query.fetchNextPage({ cancelRefetch: false }),
  };
}

export function useArchivedReports(options?: { enabled?: boolean }) {
  const { projectId, oauthAccessToken } = useAuthStore();

  const params: SignalReportsQueryParams = {
    status: INBOX_DISMISSED_STATUS_FILTER,
    ordering: buildArchiveListOrdering("updated_at", "desc"),
  };

  const query = useQuery<SignalReportsResponse>({
    queryKey: inboxKeys.archived(params),
    queryFn: () => getPostHogApiClient().getSignalReports(params),
    enabled: !!projectId && !!oauthAccessToken && (options?.enabled ?? true),
  });

  return {
    reports: query.data?.results ?? [],
    totalCount: query.data?.count ?? 0,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error?.message ?? null,
    refetch: query.refetch,
  };
}

export function useInboxReport(reportId: string | null) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<SignalReport | null>({
    queryKey: inboxKeys.detail(reportId ?? ""),
    queryFn: () => {
      if (!reportId) throw new Error("reportId is required");
      return getPostHogApiClient().getSignalReport(reportId);
    },
    enabled: !!projectId && !!oauthAccessToken && !!reportId,
  });
}

export function useSignalProcessingState(options?: { enabled?: boolean }) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<SignalProcessingStateResponse>({
    queryKey: inboxKeys.processingState,
    queryFn: () => getPostHogApiClient().getSignalProcessingState(),
    enabled: !!projectId && !!oauthAccessToken && (options?.enabled ?? true),
    refetchInterval: INBOX_REFETCH_INTERVAL_MS,
  });
}

export function useAvailableSuggestedReviewers(options?: {
  enabled?: boolean;
  query?: string;
}) {
  const { projectId, oauthAccessToken } = useAuthStore();
  const query = options?.query?.trim() ?? "";

  return useQuery<AvailableSuggestedReviewersResponse>({
    queryKey: [...inboxKeys.all, "available-reviewers", query] as const,
    queryFn: () =>
      getPostHogApiClient().getAvailableSuggestedReviewers(query || undefined),
    enabled: !!projectId && !!oauthAccessToken && (options?.enabled ?? true),
    staleTime: 5 * 60 * 1000,
    // Only poll the unfiltered list; search terms are transient and each one
    // would otherwise spawn its own background poller.
    refetchInterval: query === "" ? 60_000 : false,
  });
}

export function useInboxReportArtefacts(
  reportId: string | null,
  options?: { staleTime?: number; refetchInterval?: number | false },
) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<SignalReportArtefactsResponse>({
    queryKey: inboxKeys.artefacts(reportId ?? ""),
    queryFn: () => {
      if (!reportId) throw new Error("reportId is required");
      return getPostHogApiClient().getSignalReportArtefacts(reportId);
    },
    enabled: !!projectId && !!oauthAccessToken && !!reportId,
    // The log is a live work record — agents append artefacts while a report
    // is open, so refresh it gently rather than trusting the default staleTime.
    // List rows pass a calmer profile: reviewer suggestions rarely change mid-scroll.
    staleTime: options?.staleTime ?? 10_000,
    refetchInterval: options?.refetchInterval ?? 20_000,
  });
}

export function useCommitDiff(
  reportId: string,
  artefactId: string,
  enabled: boolean,
) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<CommitDiffResponse>({
    queryKey: inboxKeys.commitDiff(reportId, artefactId),
    queryFn: () => getPostHogApiClient().getCommitDiff(reportId, artefactId),
    // A commit's diff is immutable, so only fetch once expanded and never retry.
    enabled: enabled && !!projectId && !!oauthAccessToken,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useInboxReportSignals(reportId: string | null) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<SignalReportSignalsResponse>({
    queryKey: inboxKeys.signals(reportId ?? ""),
    queryFn: () => {
      if (!reportId) throw new Error("reportId is required");
      return getPostHogApiClient().getSignalReportSignals(reportId);
    },
    enabled: !!projectId && !!oauthAccessToken && !!reportId,
  });
}

interface UpdateSuggestedReviewersVariables {
  artefactId: string;
  content: SuggestedReviewerWriteEntry[];
  optimisticReviewers: SuggestedReviewer[];
}

export function useUpdateSuggestedReviewers(reportId: string) {
  const queryClient = useQueryClient();
  const queryKey = inboxKeys.artefacts(reportId);

  return useMutation<
    void,
    Error,
    UpdateSuggestedReviewersVariables,
    { previous: SignalReportArtefactsResponse | undefined }
  >({
    mutationFn: ({ artefactId, content }) =>
      getPostHogApiClient()
        .updateSignalReportArtefact(reportId, artefactId, content)
        .then(() => undefined),
    onMutate: async ({ artefactId, optimisticReviewers }) => {
      await queryClient.cancelQueries({ queryKey });
      const previous =
        queryClient.getQueryData<SignalReportArtefactsResponse>(queryKey);
      if (previous) {
        queryClient.setQueryData<SignalReportArtefactsResponse>(queryKey, {
          ...previous,
          results: previous.results.map((artefact) => {
            if (
              artefact.id === artefactId &&
              artefact.type === "suggested_reviewers"
            ) {
              const updatedArtefact: SuggestedReviewersArtefact = {
                ...artefact,
                type: "suggested_reviewers",
                content: optimisticReviewers,
              };
              return updatedArtefact;
            }
            return artefact;
          }),
        });
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKey, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: inboxKeys.all });
    },
  });
}

export function useDismissReport(reportId: string) {
  const queryClient = useQueryClient();

  return useMutation<
    SignalReport,
    Error,
    { reason: DismissalReasonOptionValue; note?: string }
  >({
    mutationFn: (input) =>
      getPostHogApiClient().updateSignalReportState(reportId, {
        state: "suppressed",
        dismissal_reason: input.reason,
        ...(input.note?.trim() ? { dismissal_note: input.note.trim() } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: inboxKeys.detail(reportId) });
      queryClient.invalidateQueries({ queryKey: inboxKeys.all });
    },
  });
}

export function useRefundReport(reportId: string) {
  const queryClient = useQueryClient();

  return useMutation<
    SignalReport,
    Error,
    { reason: SignalReportRefundReason; note?: string }
  >({
    mutationFn: (input) =>
      getPostHogApiClient().refundSignalReport(reportId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: inboxKeys.detail(reportId) });
      queryClient.invalidateQueries({ queryKey: inboxKeys.all });
    },
  });
}

export function useRestoreReport() {
  const queryClient = useQueryClient();

  // Resolves to whether the report was actually re-queued. Revalidate against
  // the server first so a stale row can't silently reopen an already-active
  // report.
  return useMutation<boolean, Error, string>({
    mutationFn: async (reportId) => {
      const client = getPostHogApiClient();
      const current = await client.getSignalReport(reportId);
      if (current && !isRestorableReport(current)) {
        return false;
      }
      await client.updateSignalReportState(reportId, { state: "potential" });
      return true;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: inboxKeys.all });
    },
  });
}
