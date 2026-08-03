import type { CanvasNavIntent } from "@posthog/core/canvas/freeformSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  useCreateAndOpenDashboard,
  useDashboard,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useFreeformChatStore } from "@posthog/ui/features/canvas/stores/freeformChatStore";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToChannelDashboard,
  navigateToChannelTask,
} from "@posthog/ui/router/navigationBridge";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

/**
 * Routes a canvas's allowlisted nav intent to real host navigation. channelId is
 * host-supplied (never from the iframe), so the canvas can only move within its
 * own channel. The returned callback switches exhaustively over the intent union.
 */
export function useCanvasNavigation(
  channelId: string,
): (intent: CanvasNavIntent) => void {
  const createAndOpen = useCreateAndOpenDashboard(channelId);
  return useCallback(
    (intent: CanvasNavIntent) => {
      switch (intent.target) {
        case "task":
          navigateToChannelTask(channelId, intent.taskId);
          break;
        case "new-task":
          // Via openTaskInput so a stale prefill can't leak into the composer.
          openTaskInput({ channelId });
          break;
        case "canvas":
          navigateToChannelDashboard(channelId, intent.dashboardId);
          break;
        case "new-canvas":
          void createAndOpen();
          break;
      }
    },
    [channelId, createAndOpen],
  );
}

/**
 * The home-canvas "Reset to default" affordance. Only a channel's home canvas
 * has a default template to reset to, so `isHomeCanvas` (from the canvas
 * record's own flag) gates the button. `reset` regenerates the source
 * server-side — the host publishes the template as a new head version and
 * queues its rebuild — so afterwards it drops any version browse and refetches
 * the record, version history, source, and build lifecycle. The prior version
 * stays in history, so undo can still browse (and revert to) it.
 */
export function useHomeCanvasReset(args: {
  channelId: string;
  dashboardId: string;
  threadId: string;
}): {
  isHomeCanvas: boolean;
  isResetting: boolean;
  reset: () => Promise<void>;
} {
  const { channelId, dashboardId, threadId } = args;
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const { dashboard } = useDashboard(dashboardId);
  const setBrowseVersion = useFreeformChatStore((s) => s.setBrowseVersion);
  const resetMutation = useMutation(
    trpc.dashboards.resetHomeCanvas.mutationOptions(),
  );
  const [isResetting, setIsResetting] = useState(false);

  const isHomeCanvas = dashboard?.isHome ?? false;

  const reset = useCallback(async () => {
    setIsResetting(true);
    try {
      await resetMutation.mutateAsync({ channelId });
      setBrowseVersion(threadId, null);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: trpc.dashboards.get.queryKey({ id: dashboardId }),
        }),
        queryClient.invalidateQueries({
          queryKey: trpc.dashboards.builds.queryKey({ id: dashboardId }),
        }),
        queryClient.invalidateQueries({
          queryKey: trpc.dashboards.versions.queryKey({ id: dashboardId }),
        }),
        queryClient.invalidateQueries(trpc.dashboards.source.pathFilter()),
      ]);
      toast.success("Canvas reset to default", {
        description: "Undo to browse your previous version.",
      });
    } catch (error) {
      toast.error("Couldn't reset canvas", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setIsResetting(false);
    }
  }, [
    channelId,
    dashboardId,
    threadId,
    resetMutation,
    setBrowseVersion,
    queryClient,
    trpc,
  ]);

  return { isHomeCanvas, isResetting, reset };
}
