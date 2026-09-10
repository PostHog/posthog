import { DropdownMenuSeparator, MenuLabel } from "@posthog/quill";
import { ACTIVITY_CANVAS_FLAG } from "@posthog/shared";
import {
  ActivityCanvasMenu,
  useActivityCanvasOptions,
  useSelectActivityCanvas,
} from "@posthog/ui/features/canvas/components/ActivityCanvasPane";
import { useActivityCanvasStore } from "@posthog/ui/features/canvas/stores/activityCanvasStore";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * Picks which canvas draws the Activity page. Split from the actions menu so
 * the canvas list is only queried where the flag is on.
 */
function ActivityCanvasPicker() {
  const canvasId = useActivityCanvasStore((state) => state.canvasId);
  const canvases = useActivityCanvasOptions();
  const selectCanvas = useSelectActivityCanvas();
  if (canvases.length === 0) return null;
  return (
    <>
      <DropdownMenuSeparator />
      <MenuLabel>Draw this page with</MenuLabel>
      <ActivityCanvasMenu
        canvases={canvases}
        selectedId={canvasId}
        onSelect={selectCanvas}
      />
    </>
  );
}

export function ActivityCanvasMenuSection() {
  return useFeatureFlag(ACTIVITY_CANVAS_FLAG) ? <ActivityCanvasPicker /> : null;
}
