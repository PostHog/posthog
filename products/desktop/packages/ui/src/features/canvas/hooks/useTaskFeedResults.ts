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

// Slower than a channel feed's 5s: a feed query searches the whole project's
// tasks rather than one channel, and a saved view can afford to lag a little.
const TASK_FEED_POLL_INTERVAL_MS = 15_000;

export function taskFeedResultsQueryKey(query: string) {
  return ["task-feed-results", query] as const;
}

/**
 * Compile a feed query string against live name-resolution data (teammates,
 * spaces, the viewer). `plan` is undefined while that data is still loading
 * for a query that needs it — running the query early would resolve
 * `created-by:` names to nobody and flash an empty feed.
 */
export function useFeedQueryPlan(query: string | undefined): {
  plan: FeedQueryPlan | undefined;
  isLoading: boolean;
} {
  const normalized = query?.trim() ?? "";
  const parsed = useMemo(() => parseFeedQuery(normalized), [normalized]);
  const needsMembers = parsed.tokens.some((t) => t.key === "created-by");
  const needsSpaces = parsed.tokens.some((t) => t.key === "space");

  const client = useOptionalAuthenticatedClient();
  const { data: me } = useCurrentUser({ client });
  const { members, isLoading: membersLoading } = useOrgMembers({
    enabled: needsMembers,
  });
  const { channels, isLoading: channelsLoading } = useChannels();

  const waiting =
    (needsMembers && membersLoading) || (needsSpaces && channelsLoading);

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

/**
 * The tasks a custom feed's query matches right now. Single-value filters
 * ride one server request; an OR group fans out into one request per value
 * and the pages are unioned, so `created-by:a created-by:b` finds both
 * authors' tasks however old they are. Negations and PR presence filter the
 * fetched pages client-side. The feed stores a query, never task ids, so a
 * task that stops matching simply stops appearing.
 */
export function useTaskFeedResults(query: string | undefined): {
  tasks: Task[];
  isLoading: boolean;
  /** Parse and name-resolution problems, for the query UI to surface. */
  issues: FeedQueryIssue[];
} {
  const normalized = query?.trim() ?? "";
  const { plan, isLoading: planLoading } = useFeedQueryPlan(normalized);

  const requests = plan?.requests ?? [];
  const result = useAuthenticatedQuery<Task[]>(
    // Keyed on the query string alone: the compiled params derive from it plus
    // slow-moving context (members, spaces), and each refetch reads the latest
    // closure, so a late context change corrects itself on the next poll.
    taskFeedResultsQueryKey(normalized),
    async (client) => {
      const pages = await Promise.all(
        requests.map(
          (request) =>
            client.getTasks({
              search: request.search,
              createdBy: request.createdBy,
              channel: request.channel,
              repository: request.repository,
              status: request.status,
              originProduct: request.originProduct,
              archived: request.archived,
              prState: request.prState,
              ciStatus: request.ciStatus,
            }) as unknown as Promise<Task[]>,
        ),
      );
      // Union, deduped (fanned repo filters can overlap), newest first so the
      // merged pages read like the single page each request returned.
      const byId = new Map(pages.flat().map((task) => [task.id, task]));
      return [...byId.values()].sort((a, b) =>
        b.created_at.localeCompare(a.created_at),
      );
    },
    {
      enabled: normalized !== "" && !!plan,
      gcTime: SPACE_QUERY_GC_TIME_MS,
      refetchInterval: TASK_FEED_POLL_INTERVAL_MS,
      staleTime: SPACE_QUERY_STALE_TIME_MS,
    },
  );

  const tasks = useMemo(() => {
    const fetched = result.data ?? [];
    if (!plan) return [];
    return fetched.filter((task) => plan.matches(task));
  }, [result.data, plan]);

  return {
    tasks,
    isLoading: planLoading || result.isLoading,
    issues: plan?.issues ?? [],
  };
}
