import type { TaskCommentThreadSummary } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/** Comments move at human pace, so this polls slower than the 5s thread poll. The
 *  Comments tab keeps its own faster poll for the surface people type into. */
const POLL_INTERVAL_MS = 15_000;

/**
 * Deliberately not patched by the optimistic comment writes in `useComments`: a comment you
 * just left shows up within one poll, and cross-patching two differently shaped caches is how
 * they drift apart.
 */
export function useTaskCommentActivity(
  taskId: string | undefined,
  options: { enabled?: boolean } = {},
): {
  threads: TaskCommentThreadSummary[];
  isLoading: boolean;
  /** The timeline waits on this so it draws once, complete, instead of drawing thread rows
   *  and then adding comments. */
  hasLoaded: boolean;
} {
  const enabled = options.enabled !== false && !!taskId;
  const query = useAuthenticatedQuery<TaskCommentThreadSummary[]>(
    ["task-comment-activity", taskId ?? "none"],
    (client) => client.getTaskCommentActivity(taskId as string),
    {
      enabled,
      refetchInterval: POLL_INTERVAL_MS,
      staleTime: POLL_INTERVAL_MS,
    },
  );
  return {
    threads: query.data ?? [],
    isLoading: query.isLoading,
    hasLoaded: !enabled || query.isSuccess || query.isError,
  };
}
