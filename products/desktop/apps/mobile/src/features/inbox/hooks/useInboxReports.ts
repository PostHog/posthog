import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useMemo } from "react";
import { useAuthStore } from "@/features/auth";
import {
  type DismissSignalReportInput,
  dismissSignalReport,
  getAvailableSuggestedReviewers,
  getCommitDiff,
  getSignalProcessingState,
  getSignalReport,
  getSignalReportArtefacts,
  getSignalReportSignals,
  getSignalReports,
  restoreSignalReport,
  updateSignalReportArtefact,
} from "../api";
import {
  INBOX_DISMISSED_STATUS_FILTER,
  INBOX_REFETCH_INTERVAL_MS,
} from "../constants";
import { useInboxFilterStore } from "../stores/inboxFilterStore";
import type {
  AvailableSuggestedReviewersResponse,
  CommitDiffResponse,
  SignalProcessingStateResponse,
  SignalReport,
  SignalReportArtefactsResponse,
  SignalReportSignalsResponse,
  SignalReportsQueryParams,
  SignalReportsResponse,
  SuggestedReviewer,
  SuggestedReviewerWriteEntry,
} from "../types";
import {
  buildArchiveListOrdering,
  buildPriorityFilterParam,
  buildSignalReportListOrdering,
  buildStatusFilterParam,
  buildSuggestedReviewerFilterParam,
  isRestorableReport,
} from "../utils";

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
      getSignalReports({
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
    queryFn: () => getSignalReports(params),
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
      return getSignalReport(reportId);
    },
    enabled: !!projectId && !!oauthAccessToken && !!reportId,
  });
}

export function useSignalProcessingState(options?: { enabled?: boolean }) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<SignalProcessingStateResponse>({
    queryKey: inboxKeys.processingState,
    queryFn: () => getSignalProcessingState(),
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
    queryFn: () => getAvailableSuggestedReviewers(query || undefined),
    enabled: !!projectId && !!oauthAccessToken && (options?.enabled ?? true),
    staleTime: 5 * 60 * 1000,
    // Only poll the unfiltered list; search terms are transient and each one
    // would otherwise spawn its own background poller.
    refetchInterval: query === "" ? 60_000 : false,
  });
}

export function useInboxReportArtefacts(reportId: string | null) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery<SignalReportArtefactsResponse>({
    queryKey: inboxKeys.artefacts(reportId ?? ""),
    queryFn: () => {
      if (!reportId) throw new Error("reportId is required");
      return getSignalReportArtefacts(reportId);
    },
    enabled: !!projectId && !!oauthAccessToken && !!reportId,
    // The log is a live work record — agents append artefacts while a report
    // is open, so refresh it gently rather than trusting the default staleTime.
    staleTime: 10_000,
    refetchInterval: 20_000,
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
    queryFn: () => getCommitDiff(reportId, artefactId),
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
      return getSignalReportSignals(reportId);
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
      updateSignalReportArtefact(reportId, artefactId, content),
    onMutate: async ({ artefactId, optimisticReviewers }) => {
      await queryClient.cancelQueries({ queryKey });
      const previous =
        queryClient.getQueryData<SignalReportArtefactsResponse>(queryKey);
      if (previous) {
        queryClient.setQueryData<SignalReportArtefactsResponse>(queryKey, {
          ...previous,
          results: previous.results.map((artefact) =>
            artefact.id === artefactId &&
            artefact.type === "suggested_reviewers"
              ? { ...artefact, content: optimisticReviewers }
              : artefact,
          ),
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
      queryClient.invalidateQueries({ queryKey });
    },
  });
}

export function useDismissReport(reportId: string) {
  const queryClient = useQueryClient();

  return useMutation<SignalReport, Error, DismissSignalReportInput>({
    mutationFn: (input) => dismissSignalReport(reportId, input),
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
      const current = await getSignalReport(reportId);
      if (current && !isRestorableReport(current)) {
        return false;
      }
      await restoreSignalReport(reportId);
      return true;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: inboxKeys.all });
    },
  });
}
