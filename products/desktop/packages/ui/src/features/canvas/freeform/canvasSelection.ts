import type { CanvasTextSelection } from "@posthog/core/canvas/freeformSchemas";

export function translateCanvasTextSelection(
  selection: CanvasTextSelection,
  frame: Pick<DOMRect, "left" | "top"> | undefined,
): CanvasTextSelection {
  return {
    ...selection,
    rect: {
      top: selection.rect.top + (frame?.top ?? 0),
      right: selection.rect.right + (frame?.left ?? 0),
      bottom: selection.rect.bottom + (frame?.top ?? 0),
      left: selection.rect.left + (frame?.left ?? 0),
    },
  };
}
