import type { Adapter } from "@posthog/shared";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { useDashboardEditStore } from "@posthog/ui/features/canvas/stores/dashboardEditStore";
import { useNavigate } from "@tanstack/react-router";
import { useCallback } from "react";

/**
 * The composer's canvas path: turn a prompt into a new canvas, start the
 * generation task, and open the canvas so its build streams in. Mirrors
 * `useCreateAndOpenDashboard`, which opens an empty canvas instead.
 */
export function useStartCanvasSession(args: {
  channelId: string;
  channelName: string;
  channelContext?: string;
}): {
  startCanvasSession: (opts: {
    instruction: string;
    adapter?: Adapter;
    model?: string;
    reasoningLevel?: string;
  }) => Promise<string | null>;
  isStartingCanvas: boolean;
} {
  const { channelId } = args;
  const { startNewCanvas, isStarting } = useGenerateFreeformCanvas(args);
  const setEditing = useDashboardEditStore((s) => s.setEditing);
  const navigate = useNavigate();

  const startCanvasSession = useCallback(
    async (opts: {
      instruction: string;
      adapter?: Adapter;
      model?: string;
      reasoningLevel?: string;
    }): Promise<string | null> => {
      const started = await startNewCanvas(opts);
      if (!started) return null;
      // Edit mode is what shows the generation chat beside the canvas, so the
      // user lands on the run rather than on a blank published view.
      setEditing(started.dashboardId, true);
      await navigate({
        to: "/website/$channelId/dashboards/$dashboardId",
        params: { channelId, dashboardId: started.dashboardId },
      });
      return started.dashboardId;
    },
    [channelId, navigate, setEditing, startNewCanvas],
  );

  return { startCanvasSession, isStartingCanvas: isStarting };
}
