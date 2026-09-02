import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import type { PointerEvent } from "react";
import { GridPlacementMenu } from "./GridPlacementMenu";
import type { PlacementActions } from "./placementActions";

/**
 * A card's edit affordances: the move strip along its top, the actions menu,
 * and the resize grip in its corner. Rendered only while the canvas is
 * editable, so a read-only card is the widget and nothing else.
 */
export function GridCardChrome({
  placement,
  patching,
  actions,
  onMovePointerDown,
  onResizePointerDown,
}: {
  placement: GridPlacement;
  patching: boolean;
  actions: PlacementActions;
  onMovePointerDown: (event: PointerEvent) => void;
  onResizePointerDown: (event: PointerEvent) => void;
}) {
  return (
    <>
      {/* Under the menu, which takes the corner this strip would otherwise
          offer as a drag handle. */}
      <div
        className="absolute inset-x-0 top-0 z-10 h-5 cursor-move bg-(--gray-3) opacity-0 transition-opacity group-hover:opacity-100"
        onPointerDown={onMovePointerDown}
      />
      <GridPlacementMenu
        placement={placement}
        patching={patching}
        actions={actions}
      />
      <div
        className="absolute right-0 bottom-0 z-10 h-4 w-4 cursor-nwse-resize bg-(--gray-6) opacity-0 transition-opacity group-hover:opacity-100"
        onPointerDown={onResizePointerDown}
      />
    </>
  );
}
