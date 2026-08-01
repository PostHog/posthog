import {
  inboxReportKeys,
  resolveInboxReportDetailCache,
} from "@posthog/core/inbox/inboxQuery";
import type {
  AvailableSuggestedReviewersResponse,
  SignalProcessingStateResponse,
  SignalReport,
  SignalReportArtefactsResponse,
  SignalReportSignalsResponse,
  SignalReportsQueryParams,
  SignalReportsResponse,
  SuggestedReviewersArtefact,
  SuggestedReviewerWriteEntry,
} from "@posthog/shared/types";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useInboxAvailableSuggestedReviewersStore } from "@posthog/ui/features/inbox/inboxAvailableSuggestedReviewersStore";
import { useAuthenticatedInfiniteQuery } from "@posthog/ui/hooks/useAuthenticatedInfiniteQuery";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

const REPORTS_PAGE_SIZE = 100;

export const reportKeys = inboxReportKeys;

export function useInboxReports(
  params?: SignalReportsQueryParams,
  options?: {
    enabled?: boolean;
    refetchInterval?: number | false | (() => number | false | undefined);
    refetchIntervalInBackground?: boolean;
    staleTime?: number;
  },
) {
  return useAuthenticatedQuery<SignalReportsResponse>(
    reportKeys.list(params),
    (client) => client.getSignalReports(params),
    options,
  );
}

export function useInboxReportsInfinite(
  params?: SignalReportsQueryParams,
  options?: {
    enabled?: boolean;
    refetchInterval?:
      | number
      | false
      | (() => number | false | undefined)
      | ((query: unknown) => number | false | undefined);
    refetchIntervalInBackground?: boolean;
    staleTime?: number;
  },
) {
  const query = useAuthenticatedInfiniteQuery<SignalReportsResponse, number>(
    reportKeys.infiniteList(params),
    (client, offset) =>
      client.getSignalReports({
        ...params,
        limit: REPORTS_PAGE_SIZE,
        offset,
      }),
    {
      enabled: options?.enabled,
      initialPageParam: 0,
      getNextPageParam: (lastPage, allPages) => {
        const loaded = allPages.reduce((n, p) => n + p.results.length, 0);
        return loaded < lastPage.count ? loaded : undefined;
      },
      refetchInterval: options?.refetchInterval,
      refetchIntervalInBackground: options?.refetchIntervalInBackground,
      staleTime: options?.staleTime,
    },
  );

  const allReports = useMemo(
    () => query.data?.pages.flatMap((p) => p.results) ?? [],
    [query.data?.pages],
  );

  const totalCount = query.data?.pages[0]?.count ?? 0;

  return { ...query, allReports, totalCount };
}

export function useInboxAvailableSuggestedReviewers(options?: {
  enabled?: boolean;
  staleTime?: number;
  query?: string;
}) {
  const authState = useAuthStateValue((state) => state);
  const authIdentity = getAuthIdentity(authState);
  const reviewerQuery = options?.query?.trim() ?? "";
  const shouldUseCachedBaseList = reviewerQuery.length === 0;
  const cachedEntry = useInboxAvailableSuggestedReviewersStore((state) =>
    shouldUseCachedBaseList
      ? state.getReviewersForAuthIdentity(authIdentity)
      : null,
  );
  const setReviewersForAuthIdentity = useInboxAvailableSuggestedReviewersStore(
    (state) => state.setReviewersForAuthIdentity,
  );

  const query = useAuthenticatedQuery<AvailableSuggestedReviewersResponse>(
    reportKeys.availableSuggestedReviewers(
      authIdentity ? `${authIdentity}:${reviewerQuery}` : null,
    ),
    (client) => client.getAvailableSuggestedReviewers(reviewerQuery),
    {
      enabled: !!authIdentity && (options?.enabled ?? true),
      staleTime: options?.staleTime ?? 5 * 60 * 1000,
      refetchOnMount: "always",
      refetchInterval: 60_000,
      refetchIntervalInBackground: true,
      placeholderData:
        shouldUseCachedBaseList && cachedEntry
          ? {
              results: cachedEntry.reviewers,
              count: cachedEntry.reviewers.length,
            }
          : undefined,
    },
  );

  useEffect(() => {
    if (!authIdentity || !query.data || !shouldUseCachedBaseList) {
      return;
    }

    setReviewersForAuthIdentity(authIdentity, query.data.results);
  }, [
    authIdentity,
    query.data,
    setReviewersForAuthIdentity,
    shouldUseCachedBaseList,
  ]);

  return query;
}

export function useInboxSignalProcessingState(options?: {
  enabled?: boolean;
  refetchInterval?: number | false | (() => number | false | undefined);
  refetchIntervalInBackground?: boolean;
  staleTime?: number;
}) {
  return useAuthenticatedQuery<SignalProcessingStateResponse>(
    reportKeys.signalProcessingState,
    (client) => client.getSignalProcessingState(),
    options,
  );
}

export function useInboxReportById(
  reportId: string | null,
  options?: {
    enabled?: boolean;
    refetchInterval?: number | false | (() => number | false | undefined);
    refetchIntervalInBackground?: boolean;
    staleTime?: number;
  },
) {
  const queryClient = useQueryClient();

  return useAuthenticatedQuery<SignalReport | null>(
    reportKeys.detail(reportId ?? ""),
    (client) => client.getSignalReport(reportId ?? ""),
    {
      enabled: !!reportId && (options?.enabled ?? true),
      initialData: () => {
        if (!reportId) return undefined;
        return (
          resolveInboxReportDetailCache(queryClient, reportId) ?? undefined
        );
      },
      initialDataUpdatedAt: () => {
        if (!reportId) return undefined;
        return resolveInboxReportDetailCache(queryClient, reportId)
          ? 0
          : undefined;
      },
      placeholderData: (previous) => previous,
      refetchInterval: options?.refetchInterval,
      refetchIntervalInBackground: options?.refetchIntervalInBackground,
      staleTime: options?.staleTime,
    },
  );
}

export function useInboxReportArtefacts(
  reportId: string,
  options?: {
    enabled?: boolean;
    staleTime?: number;
    refetchInterval?: number;
    refetchOnWindowFocus?: boolean;
  },
) {
  const { enabled, ...queryOptions } = options ?? {};
  return useAuthenticatedQuery<SignalReportArtefactsResponse>(
    reportKeys.artefacts(reportId),
    (client) => client.getSignalReportArtefacts(reportId),
    {
      enabled: !!reportId && (enabled ?? true),
      ...queryOptions,
    },
  );
}

export function useInboxReportSignals(
  reportId: string,
  options?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<SignalReportSignalsResponse>(
    reportKeys.signals(reportId),
    (client) => client.getSignalReportSignals(reportId),
    { enabled: !!reportId && (options?.enabled ?? true) },
  );
}

interface UpdateSuggestedReviewersVariables {
  artefactId: string;
  /** Reviewer list sent to the server (it appends a new suggested_reviewers status row). */
  content: SuggestedReviewerWriteEntry[];
  /** Read-shape list used to optimistically show the new current reviewers. */
  optimisticReviewers: SuggestedReviewersArtefact["content"];
}

/**
 * Edits a report's suggested reviewers. The server appends a new `suggested_reviewers` status
 * artefact (latest-wins), so the work-log keeps the full history of changes. We optimistically
 * append a synthetic latest row — mirroring the server — so the detail pane reflects the change
 * instantly (immediate apply); the refetch on settle reconciles it with the real row.
 */
export function useUpdateSuggestedReviewers(reportId: string) {
  const queryClient = useQueryClient();
  const queryKey = reportKeys.artefacts(reportId);

  return useAuthenticatedMutation<
    SuggestedReviewersArtefact,
    Error,
    UpdateSuggestedReviewersVariables
  >(
    (client, { artefactId, content }) =>
      client.updateSignalReportArtefact(reportId, artefactId, content),
    {
      onMutate: async ({ optimisticReviewers }) => {
        await queryClient.cancelQueries({ queryKey });
        const previous =
          queryClient.getQueryData<SignalReportArtefactsResponse>(queryKey);

        if (previous) {
          // Append a synthetic latest row rather than mutating the current one — "current
          // reviewers" is derived as the latest suggested_reviewers artefact, so a row stamped
          // now wins, and the prior row stays in the log as history (matching the server).
          const optimisticRow: SuggestedReviewersArtefact = {
            id: `optimistic-${Date.now()}`,
            type: "suggested_reviewers",
            content: optimisticReviewers,
            created_at: new Date().toISOString(),
          };
          queryClient.setQueryData<SignalReportArtefactsResponse>(queryKey, {
            ...previous,
            results: [...previous.results, optimisticRow],
            count: previous.count + 1,
          });
        }

        return { previous };
      },
      onError: (error, _variables, context) => {
        const previous = (
          context as { previous?: SignalReportArtefactsResponse }
        )?.previous;
        if (previous) {
          queryClient.setQueryData(queryKey, previous);
        }
        toast.error(error.message || "Failed to update suggested reviewers");
      },
      onSettled: () => {
        queryClient.invalidateQueries({ queryKey });
      },
    },
  );
}
