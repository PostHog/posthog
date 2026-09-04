import { CANVAS_V2_TAG } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import type { ReactElement } from "react";

export function CanvasVersionTag(): ReactElement {
  return (
    <span className="shrink-0 rounded-sm bg-fill-hover px-1 py-px font-medium text-[10px] text-muted-foreground leading-none">
      {CANVAS_V2_TAG}
    </span>
  );
}
