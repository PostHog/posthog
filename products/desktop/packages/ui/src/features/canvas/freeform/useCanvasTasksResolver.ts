import { buildCanvasTaskSummaries } from "@posthog/core/canvas/canvasTasks";
import type {
  CanvasTasksInput,
  CanvasTasksResult,
} from "@posthog/core/canvas/freeformSchemas";
import { sessionStore } from "@posthog/core/sessions/sessionStore";
import type { Task } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { taskKeys } from "../../tasks/taskKeys";

// How stale the task LIST may be when a canvas polls ph.tasks. The list only
// carries identity + run metadata; the live signals a board watches (waiting/
// running/needs-permission) come from the session-store snapshot taken on every
// call, so a short list window costs no status freshness. Deliberately lazy:
// nothing is fetched until a canvas actually calls ph.tasks — canvases that
// never use it add zero poll load (idle-poll churn is this app's top drain).
const TASKS_STALE_MS = 15_000;

/**
 * The renderer-local resolver behind a canvas's `ph.tasks` — the user's tasks
 * from the shared tasks query cache (same key as `useTasks`, so reads dedupe
 * with the sidebar's poll) joined with the live session store by the tested
 * core builder. Sessions are snapshotted at call time, not subscribed, so
 * streamed events never re-render the canvas host; a board polls ph.tasks from
 * inside the iframe instead. Pass the returned resolver to
 * `handleFreeformDataRequest`'s context.
 */
export function useCanvasTasksResolver(): (
  input: CanvasTasksInput,
) => Promise<CanvasTasksResult> {
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();
  const { data: me } = useMeQuery();
  // Plain deps, no latest-value ref: the client identity only moves on an auth
  // state change and meId is a stable scalar, so the resolver (and the
  // onDataRequest callbacks it feeds) rebuilds rarely — and never mid-request.
  const meId = me?.id;

  return useCallback(
    async (input: CanvasTasksInput) => {
      if (!client || !meId) {
        throw new Error("ph.tasks requires a signed-in app");
      }
      // Same key shape as useTasks' default view (undefined filters drop out
      // of the hash), so this shares the sidebar's cache entry instead of
      // double-fetching.
      const tasks = await queryClient.fetchQuery({
        queryKey: taskKeys.list({ createdBy: meId }),
        queryFn: () =>
          client.getTasks({ createdBy: meId }) as unknown as Promise<Task[]>,
        staleTime: TASKS_STALE_MS,
        meta: AUTH_SCOPED_QUERY_META,
      });
      return buildCanvasTaskSummaries(
        tasks,
        sessionStore.getState().sessions,
        input,
      );
    },
    [queryClient, client, meId],
  );
}
