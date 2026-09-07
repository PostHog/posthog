import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";

const TASK_CANVASES_POLL_INTERVAL_MS = 30_000;

/**
 * Canvases a task generated, read from the canvas rows themselves. The task's
 * thread announces a canvas only on its first publish, and only for some
 * callers, so a thread-only artifact list hides canvases that exist.
 */
export function useTaskCanvases(taskId: string | undefined): DashboardRecord[] {
  const trpc = useHostTRPC();
  const { data } = useQuery(
    trpc.dashboards.listForTask.queryOptions(
      { taskId: taskId ?? "" },
      {
        enabled: !!taskId,
        meta: AUTH_SCOPED_QUERY_META,
        refetchInterval: TASK_CANVASES_POLL_INTERVAL_MS,
      },
    ),
  );
  return data ?? [];
}
