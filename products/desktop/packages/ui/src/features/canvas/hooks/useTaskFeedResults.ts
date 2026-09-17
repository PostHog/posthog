import {
  type FeedQueryIssue,
  type FeedQueryPlan,
  type FeedQueryToken,
  parseFeedQuery,
  planFeedQuery,
} from "@posthog/core/tasks/feedQuery";
import type { SignalReport, Task } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";

const TASK_FEED_POLL_INTERVAL_MS = 15_000;
const TASK_FEED_MAX_PAGES = 5;
const REPORT_FEED_PAGE_SIZE = 100;
export const taskFeedResultsQueryRoot = ["task-feed-results"] as const;

function isPersonToken(token: FeedQueryToken): boolean {
  return (
    token.key === "created-by" ||
    token.key === "commented-by" ||
    token.key === "mentions" ||
    token.key === "involves"
  );
}

function isCurrentUserToken(token: FeedQueryToken): boolean {
  const value = token.value.toLowerCase();
  return value === "@me" || value === "me";
}

export function taskFeedResultsQueryKey(query: string) {
  return [...taskFeedResultsQueryRoot, query] as const;
}

export function useFeedQueryPlan(query: string | undefined): {
  canRetry: boolean;
  error: Error | null;
  errorMessage: string | null;
  plan: FeedQueryPlan | undefined;
  isLoading: boolean;
  refetch: () => void;
} {
  const normalized = query?.trim() ?? "";
  const parsed = useMemo(() => parseFeedQuery(normalized), [normalized]);
  const needsMembers = parsed.tokens.some(
    (token) => isPersonToken(token) && !isCurrentUserToken(token),
  );
  const needsSpaces = parsed.tokens.some((t) => t.key === "space");
  const needsCurrentUser = parsed.tokens.some(
    (token) => isPersonToken(token) && isCurrentUserToken(token),
  );

  const client = useOptionalAuthenticatedClient();
  const { data: me, isLoading: currentUserLoading } = useCurrentUser({
    client,
  });
  const {
    members,
    error: membersError,
    isComplete: membersComplete,
    isLoading: membersLoading,
    refetch: refetchMembers,
  } = useOrgMembers({ enabled: needsMembers });
  const { channels, isLoading: channelsLoading } = useChannels();

  const memberLookupFailed = needsMembers && membersError !== null;
  const memberLookupIncomplete = needsMembers && !membersComplete;
  const waiting =
    (needsMembers && membersLoading) ||
    (needsCurrentUser && currentUserLoading) ||
    (needsSpaces && channelsLoading);

  const plan = useMemo(() => {
    if (
      normalized === "" ||
      waiting ||
      memberLookupFailed ||
      memberLookupIncomplete
    ) {
      return undefined;
    }
    return planFeedQuery(parsed, {
      members,
      spaces: channels.map((c) => ({ id: c.id, name: c.name })),
      me: me ?? null,
      reportsEnabled: false,
    });
  }, [
    normalized,
    waiting,
    memberLookupFailed,
    memberLookupIncomplete,
    parsed,
    members,
    channels,
    me,
  ]);

  return {
    canRetry: memberLookupFailed,
    error: memberLookupFailed
      ? membersError
      : memberLookupIncomplete
        ? new Error("Organization member lookup is incomplete")
        : null,
    errorMessage: memberLookupFailed
      ? "Couldn't load organization members. Try again."
      : memberLookupIncomplete
        ? "Organization member lookup is incomplete. This search cannot verify every teammate."
        : null,
    isLoading: normalized !== "" && waiting,
    plan,
    refetch: refetchMembers,
  };
}

export function useTaskFeedResults(query: string | undefined): {
  canRetry: boolean;
  error: Error | null;
  errorMessage: string | null;
  isComplete: boolean;
  isFetching: boolean;
  isLoading: boolean;
  issues: FeedQueryIssue[];
  /** What the feed carries: tasks (the default) or reports (`type:report`). */
  mode: "tasks" | "reports";
  refetch: () => void;
  reports: SignalReport[];
  tasks: Task[];
} {
  const normalized = query?.trim() ?? "";
  const {
    canRetry: planCanRetry,
    error: planError,
    errorMessage: planErrorMessage,
    plan,
    isLoading: planLoading,
    refetch: refetchPlan,
  } = useFeedQueryPlan(normalized);

  const requests = plan?.requests ?? [];
  const reportsMode = plan?.mode === "reports";
  const reportChannelId = plan?.reportChannelId;
  const result = useAuthenticatedQuery<{
    tasks: Task[];
    reports: SignalReport[];
    isComplete: boolean;
  }>(
    taskFeedResultsQueryKey(normalized),
    async (client) => {
      if (reportsMode) {
        const response = await client.getSignalReports({
          ordering: "-created_at",
          limit: REPORT_FEED_PAGE_SIZE,
          ...(reportChannelId ? { channel_id: reportChannelId } : {}),
        });
        return {
          tasks: [],
          reports: response.results,
          isComplete: response.results.length >= response.count,
        };
      }
      const pages = await Promise.all(
        requests.map((request) =>
          client.getTasksWithStatus(request, {
            maxPages: TASK_FEED_MAX_PAGES,
          }),
        ),
      );
      const byId = new Map<string, Task>();
      for (const page of pages) {
        for (const task of page.tasks) {
          byId.set(task.id, task);
        }
      }
      return {
        tasks: [...byId.values()].sort((a, b) =>
          b.created_at.localeCompare(a.created_at),
        ),
        reports: [],
        isComplete: pages.every((page) => page.isComplete),
      };
    },
    {
      enabled: normalized !== "" && !!plan,
      gcTime: SPACE_QUERY_GC_TIME_MS,
      refetchInterval: TASK_FEED_POLL_INTERVAL_MS,
      staleTime: SPACE_QUERY_STALE_TIME_MS,
    },
  );

  const tasks = useMemo(() => {
    const fetched = result.data?.tasks ?? [];
    if (!plan) return [];
    return fetched.filter((task) => plan.matches(task));
  }, [result.data, plan]);

  const reports = useMemo(() => {
    const fetched = result.data?.reports ?? [];
    const matchesReport = plan?.matchesReport;
    if (!matchesReport) return fetched;
    return fetched.filter((report) => matchesReport(report));
  }, [result.data, plan]);

  return {
    canRetry: planError ? planCanRetry : result.error !== null,
    error: planError ?? result.error ?? null,
    errorMessage:
      planErrorMessage ??
      (result.error
        ? `Couldn't load matching ${reportsMode ? "reports" : "tasks"}. Try again.`
        : null),
    isComplete: result.data?.isComplete ?? false,
    isFetching: result.isFetching,
    isLoading: planLoading || result.isLoading,
    issues: plan?.issues ?? [],
    mode: plan?.mode ?? "tasks",
    refetch: () => {
      if (planError) {
        refetchPlan();
        return;
      }
      void result.refetch();
    },
    reports,
    tasks,
  };
}
