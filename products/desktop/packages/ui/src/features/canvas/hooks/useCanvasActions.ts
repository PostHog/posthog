import type { CanvasType } from "@posthog/core/canvas/dashboardSchemas";
import type { ChannelsSurface } from "@posthog/shared/analytics-events";
import { useSketchpadMutations } from "@posthog/ui/features/sketchpad/hooks/useSketchpadMutations";
import {
  navigateToChannelDashboard,
  navigateToSpaceSketchpad,
} from "@posthog/ui/router/navigationBridge";
import {
  canvasShareUrl,
  sketchpadShareUrl,
} from "@posthog/ui/utils/posthogLinks";
import { useCallback, useMemo } from "react";
import { copyCanvasUrl } from "../utils/copyCanvasLink";
import { useDashboardMutations } from "./useDashboards";

export function useCanvasActions() {
  const { deleteDashboard, setPinned, fileDashboard } = useDashboardMutations();
  const { removeSketchpad, setSketchpadPinned, fileSketchpad } =
    useSketchpadMutations();
  const openCanvas = useCallback(
    (channelId: string, id: string, type: CanvasType): void => {
      if (type === "sketchpad") navigateToSpaceSketchpad(channelId, id);
      else navigateToChannelDashboard(channelId, id);
    },
    [],
  );
  const setCanvasPinned = useCallback(
    async (id: string, pinned: boolean, type: CanvasType): Promise<void> => {
      if (type === "sketchpad") await setSketchpadPinned(id, pinned);
      else await setPinned(id, pinned);
    },
    [setPinned, setSketchpadPinned],
  );
  const fileCanvas = useCallback(
    async (id: string, channelId: string, type: CanvasType): Promise<void> => {
      if (type === "sketchpad") await fileSketchpad(id, channelId);
      else await fileDashboard(id, channelId);
    },
    [fileDashboard, fileSketchpad],
  );
  const removeCanvas = useCallback(
    async (id: string, type: CanvasType): Promise<void> => {
      if (type === "sketchpad") await removeSketchpad(id);
      else await deleteDashboard(id);
    },
    [deleteDashboard, removeSketchpad],
  );
  const copyCanvas = useCallback(
    (
      channelId: string,
      id: string,
      type: CanvasType,
      surface: ChannelsSurface,
    ): Promise<void> => {
      const url =
        type === "sketchpad"
          ? sketchpadShareUrl(channelId, id)
          : canvasShareUrl(channelId, id);
      return copyCanvasUrl(url, channelId, id, surface);
    },
    [],
  );
  return useMemo(
    () => ({
      openCanvas,
      setCanvasPinned,
      fileCanvas,
      removeCanvas,
      copyCanvas,
    }),
    [openCanvas, setCanvasPinned, fileCanvas, removeCanvas, copyCanvas],
  );
}
