import {
  type FeedQueryIssue,
  type FeedQueryPlan,
  parseFeedQuery,
  planFeedQuery,
} from "@posthog/core/tasks/feedQuery";
import type { Task } from "@posthog/shared/domain-types";
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

export function taskFeedResultsQueryKey(query: string) {
  return ["task-feed-results", query] as const;
}

export function useFeedQueryPlan(query: string | undefined): {
  plan: FeedQueryPlan | undefined;
  isLoading: boolean;
} {
  const normalized = query?.trim() ?? "";
  const parsed = useMemo(() => parseFeedQuery(normalized), [normalized]);
  const needsMembers = parsed.tokens.some(
    (t) =>
      t.key === "created-by" ||
      t.key === "commented-by" ||
      t.key === "mentions" ||
      t.key === "involves",
  );
  const needsSpaces = parsed.tokens.some((t) => t.key === "space");

  const needsCurrentUser = parsed.tokens.some(
    (token) =>
      (token.key === "created-by" ||
        token.key === "commented-by" ||
        token.key === "mentions" ||
        token.key === "involves") &&
      (token.value.toLowerCase() === "@me" ||
        token.value.toLowerCase() === "me"),
  );

  const client = useOptionalAuthenticatedClient();
  const { data: me, isLoading: currentUserLoading } = useCurrentUser({
    client,
  });
  const { members, isLoading: membersLoading } = useOrgMembers({
    enabled: needsMembers,
  });
  const { channels, isLoading: channelsLoading } = useChannels();

  const waiting =
    (needsMembers && membersLoading) ||
    (needsCurrentUser && currentUserLoading) ||
    (needsSpaces && channelsLoading);

  const plan = useMemo(() => {
    if (normalized === "" || waiting) return undefined;
    return planFeedQuery(parsed, {
      members,
      spaces: channels.map((c) => ({ id: c.id, name: c.name })),
      me: me ?? null,
    });
  }, [normalized, waiting, parsed, members, channels, me]);

  return { plan, isLoading: normalized !== "" && waiting };
}

export function useTaskFeedResults(query: string | undefined): {
  tasks: Task[];
  isComplete: boolean;
  isLoading: boolean;
  issues: FeedQueryIssue[];
} {
  const normalized = query?.trim() ?? "";
  const { plan, isLoading: planLoading } = useFeedQueryPlan(normalized);

  const requests = plan?.requests ?? [];
  const result = useAuthenticatedQuery<{ tasks: Task[]; isComplete: boolean }>(
    taskFeedResultsQueryKey(normalized),
    async (client) => {
      const pages = await Promise.all(
        requests.map((request) =>
          client.getTasksWithStatus(request, {
            maxPages: TASK_FEED_MAX_PAGES,
          }),
        ),
      );
      const byId = new Map(
        pages.flatMap((page) => page.tasks).map((task) => [task.id, task]),
      );
      return {
        tasks: [...byId.values()].sort((a, b) =>
          b.created_at.localeCompare(a.created_at),
        ),
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

  return {
    tasks,
    isComplete: result.data?.isComplete ?? false,
    isLoading: planLoading || result.isLoading,
    issues: plan?.issues ?? [],
  };
}
