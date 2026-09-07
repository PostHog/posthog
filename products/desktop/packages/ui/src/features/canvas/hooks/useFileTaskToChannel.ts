import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { useNavigate, useParams, useRouter } from "@tanstack/react-router";
import { useCallback } from "react";

const latestRouteFilings = new WeakMap<object, Map<string, symbol>>();

function latestRouteFilingsFor(router: object): Map<string, symbol> {
  const existing = latestRouteFilings.get(router);
  if (existing) return existing;
  const filings = new Map<string, symbol>();
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
}): (channelId: string, taskId: string, taskTitle: string) => Promise<void> {
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
      const filingToken = Symbol(taskId);
      latestRouteFilingsFor(router).set(taskId, filingToken);
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
        if (
          latestRouteFilingsFor(router).get(taskId) === filingToken &&
          moveActiveRoute &&
          router.state.location.pathname === optimisticPath
        ) {
          if (activeChannelId) {
            void navigate({
              to: "/spaces/$channelId/tasks/$taskId",
              params: { channelId: activeChannelId, taskId },
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
        if (latestRouteFilingsFor(router).get(taskId) === filingToken) {
          latestRouteFilingsFor(router).delete(taskId);
        }
      }
    },
    [activeChannelId, activeTaskId, channels, fileTask, navigate, router],
  );
}
