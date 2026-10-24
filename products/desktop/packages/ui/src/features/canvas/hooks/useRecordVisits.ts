import { useCanvasViewedStore } from "@posthog/ui/features/canvas/stores/canvasViewedStore";
import { useSpaceViewedStore } from "@posthog/ui/features/canvas/stores/spaceViewedStore";
import { useEffect } from "react";

/** Records when the viewer opens a space or a canvas, for "recent" sorts. */
export function useRecordVisits(
  spaceId: string | undefined,
  canvasId: string | undefined,
): void {
  const markSpaceViewed = useSpaceViewedStore((state) => state.markSpaceViewed);
  const markCanvasViewed = useCanvasViewedStore(
    (state) => state.markCanvasViewed,
  );
  useEffect(() => {
    if (spaceId) markSpaceViewed(spaceId, Date.now());
  }, [spaceId, markSpaceViewed]);
  useEffect(() => {
    if (canvasId) markCanvasViewed(canvasId, Date.now());
  }, [canvasId, markCanvasViewed]);
}
