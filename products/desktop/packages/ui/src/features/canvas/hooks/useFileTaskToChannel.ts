import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { useNavigate, useParams, useRouter } from "@tanstack/react-router";
import { useCallback } from "react";

interface RouteFiling {
  /**
   * The route the task sat on before the first filing of this run, or null
   * when the task was not the open route.
   */
  origin: { channelId: string | undefined } | null;
  /** Marks the newest filing, so an older failure cannot move the route. */
  token: symbol;
}

const latestRouteFilings = new WeakMap<object, Map<string, RouteFiling>>();

function latestRouteFilingsFor(router: object): Map<string, RouteFiling> {
  const existing = latestRouteFilings.get(router);
  if (existing) return existing;
  const filings = new Map<string, RouteFiling>();
  latestRouteFilings.set(router, filings);
  return filings;
}

/**
 * Files a task to a space and reports the outcome, naming the space in the
 * success toast. Extracted so the row menu and the native context menu file
 * tasks the same way — filing is a mutation plus the two toasts that make it
 * legible, and duplicating that is how the two paths drift.
 */
export function useFileTaskToChannel(options?: {
  enabled?: boolean;
}): (channelId: string, taskId: string) => Promise<void> {
  const { fileTask } = useChannelTaskMutations();
  const { channels } = useChannels(options);
  const navigate = useNavigate();
  const router = useRouter();
  const activeTaskId = useParams({
    strict: false,
    select: (params) => params.taskId,
  });
  const activeChannelId = useParams({
    strict: false,
    select: (params) => params.channelId,
  });

  return useCallback(
    async (channelId: string, taskId: string) => {
      const routeFilings = latestRouteFilingsFor(router);
      const filingToken = Symbol(taskId);
      // Hold the origin of the first filing in a run. A filing that starts
      // while another is in flight reads an activeChannelId that the earlier
      // optimistic move already changed, so a rollback to it would leave the
      // route on a space the task never entered.
      const origin =
        routeFilings.get(taskId)?.origin ??
        (activeTaskId === taskId ? { channelId: activeChannelId } : null);
      routeFilings.set(taskId, { origin, token: filingToken });
      const moveActiveRoute =
        activeTaskId === taskId && activeChannelId !== channelId;
      const filing = fileTask(channelId, taskId);
      const routeMove = moveActiveRoute
        ? navigate({
            to: "/spaces/$channelId/tasks/$taskId",
            params: { channelId, taskId },
            replace: true,
          })
        : null;

      try {
        await filing;
        const channelName = channels.find(
          (channel) => channel.id === channelId,
        )?.name;
        toast.success(channelName ? `Filed to ${channelName}` : "Task filed");
      } catch (error) {
        await routeMove?.catch(() => undefined);
        const optimisticPath = `/spaces/${channelId}/tasks/${taskId}`;
        // The pathname match is what says the route needs restoring, rather
        // than whether this call moved it: a retry to the same destination
        // moves nothing and still leaves the route on the failed space.
        if (
          routeFilings.get(taskId)?.token === filingToken &&
          origin &&
          origin.channelId !== channelId &&
          router.state.location.pathname === optimisticPath
        ) {
          if (origin.channelId) {
            void navigate({
              to: "/spaces/$channelId/tasks/$taskId",
              params: { channelId: origin.channelId, taskId },
              replace: true,
            });
          } else {
            void navigate({
              to: "/tasks/$taskId",
              params: { taskId },
              replace: true,
            });
          }
        }
        toast.error("Couldn't file task", {
          description: error instanceof Error ? error.message : String(error),
        });
      } finally {
        if (routeFilings.get(taskId)?.token === filingToken) {
          routeFilings.delete(taskId);
        }
      }
    },
    [activeChannelId, activeTaskId, channels, fileTask, navigate, router],
  );
}
