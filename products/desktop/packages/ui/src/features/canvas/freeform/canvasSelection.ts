import type { CanvasTextSelection } from "@posthog/core/canvas/freeformSchemas";
import type { CaptureBounds } from "@posthog/ui/features/code-editor/components/selectionScreenshot";

export type HostCanvasTextSelection = CanvasTextSelection & {
  frame?: CaptureBounds;
};

export function translateCanvasTextSelection(
  selection: CanvasTextSelection,
  frame: Pick<DOMRect, "left" | "top" | "right" | "bottom"> | undefined,
): HostCanvasTextSelection {
  return {
    ...selection,
    rect: {
      top: selection.rect.top + (frame?.top ?? 0),
      right: selection.rect.right + (frame?.left ?? 0),
      bottom: selection.rect.bottom + (frame?.top ?? 0),
      left: selection.rect.left + (frame?.left ?? 0),
    },
    frame: frame
      ? {
          top: frame.top,
          left: frame.left,
          right: frame.right,
          bottom: frame.bottom,
        }
      : undefined,
  };
}
