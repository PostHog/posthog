import type { CanvasNavIntent } from "@posthog/core/canvas/freeformSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useCreateAndOpenDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useFreeformChatStore } from "@posthog/ui/features/canvas/stores/freeformChatStore";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToChannelDashboard,
  navigateToChannelNewTask,
  navigateToChannelTask,
} from "@posthog/ui/router/navigationBridge";
import { useMutation } from "@tanstack/react-query";
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
          navigateToChannelNewTask(channelId);
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
 * The home-canvas "Reset to default" affordance. Only a channel's home canvas has
 * a default template to reset to, so `isHomeCanvas` gates the button. `reset`
 * rebuilds it from the template (the host appends the regenerated source as a new
 * version and keeps the prior one for undo) and adopts the fresh head into the
 * thread via syncFromRecord, so the edit stays recoverable.
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
  const { channels } = useChannels();
  const syncFromRecord = useFreeformChatStore((s) => s.syncFromRecord);
  const resetMutation = useMutation(
    trpc.dashboards.resetHomeCanvas.mutationOptions(),
  );
  const [isResetting, setIsResetting] = useState(false);

  const isHomeCanvas = channels.some(
    (c) => c.id === channelId && c.homeCanvasId === dashboardId,
  );

  const reset = useCallback(async () => {
    setIsResetting(true);
    try {
      const record = await resetMutation.mutateAsync({ channelId });
      syncFromRecord(threadId, {
        code: record.code,
        versions: record.versions,
        currentVersionId: record.currentVersionId,
        templateId: record.templateId,
        context: record.context,
      });
      toast.success("Canvas reset to default", {
        description: "Undo to restore your previous version.",
      });
    } catch (error) {
      toast.error("Couldn't reset canvas", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setIsResetting(false);
    }
  }, [channelId, threadId, resetMutation, syncFromRecord]);

  return { isHomeCanvas, isResetting, reset };
}
