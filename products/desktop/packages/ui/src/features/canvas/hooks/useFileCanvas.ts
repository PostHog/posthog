import {
  ANALYTICS_EVENTS,
  type ChannelsSurface,
} from "@posthog/shared/analytics-events";
import { useDashboardMutations } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback } from "react";

export interface FileCanvasOptions {
  dashboardId: string;
  /** The space the canvas is filed under now, for the analytics `channel_id`. */
  sourceChannelId: string;
  /** The space to move the canvas to. */
  targetChannelId: string;
  /** Target space name, for the success toast. */
  targetName?: string;
  surface: ChannelsSurface;
}

/**
 * File a canvas into another space, toasting the outcome and tracking it. Shared
 * by every "File to…" affordance (sidebar row, canvas header, dashboards grid)
 * so the mutation, feedback, and analytics stay in one place.
 */
export function useFileCanvas(): (opts: FileCanvasOptions) => Promise<void> {
  const { fileDashboard } = useDashboardMutations();

  return useCallback(
    async ({
      dashboardId,
      sourceChannelId,
      targetChannelId,
      targetName,
      surface,
    }) => {
      try {
        await fileDashboard(dashboardId, targetChannelId);
        toast.success(targetName ? `Filed to ${targetName}` : "Canvas filed");
        track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
          action_type: "file",
          surface,
          channel_id: sourceChannelId,
          target_channel_id: targetChannelId,
          dashboard_id: dashboardId,
          success: true,
        });
      } catch (error) {
        toast.error("Couldn't file canvas", {
          description: error instanceof Error ? error.message : String(error),
        });
        track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
          action_type: "file",
          surface,
          channel_id: sourceChannelId,
          target_channel_id: targetChannelId,
          dashboard_id: dashboardId,
          success: false,
        });
      }
    },
    [fileDashboard],
  );
}
