import { resolvePanelDrag } from "@posthog/ui/features/navigation/rightPanelGeometry";
import {
  currentRightPanelSide,
  openRightPanelSide,
} from "@posthog/ui/features/navigation/rightPanelSide";
import {
  DEFAULT_RIGHT_PANEL_SIDE,
  type RightPanelSide,
  useRightPanelStore,
} from "@posthog/ui/features/navigation/rightPanelStore";
import { ResizeHandle } from "@posthog/ui/primitives/ResizeHandle";
import React from "react";

/**
 * The panel is anchored to the row's right edge, so the width being asked for
 * is the pointer's distance from it. `resolvePanelDrag` says what each distance
 * means; this carries it out.
 */
export function PanelResizeHandle({
  taskId,
  panelRef,
  rowWidth,
}: {
  taskId: string;
  panelRef: React.RefObject<HTMLDivElement | null>;
  rowWidth: number;
}) {
  const isResizing = useRightPanelStore((s) => s.isResizing);
  const setIsResizing = useRightPanelStore((s) => s.setIsResizing);

  // Captured on mousedown. The width is what a drag-to-close puts back, since
  // closing walks the stored width down to the floor on its way out.
  const start = React.useRef({
    right: 0,
    width: 0,
    side: DEFAULT_RIGHT_PANEL_SIDE as RightPanelSide,
  });
  const closed = React.useRef(false);

  return (
    <ResizeHandle
      edge="left"
      tooltip="Resize"
      isResizing={isResizing}
      setIsResizing={setIsResizing}
      onDragStart={() => {
        start.current = {
          right: panelRef.current?.getBoundingClientRect().right ?? 0,
          width: useRightPanelStore.getState().width,
          side: currentRightPanelSide(taskId) ?? DEFAULT_RIGHT_PANEL_SIDE,
        };
        closed.current = false;
      }}
      onDrag={(event) => {
        const { setWidth, setExpandedForKey, expandedByKey } =
          useRightPanelStore.getState();
        const drag = resolvePanelDrag({
          pointer: start.current.right - event.clientX,
          rowWidth,
          open: currentRightPanelSide(taskId) != null,
          expanded: expandedByKey[taskId] ?? false,
        });

        switch (drag.action) {
          case "hold":
            return;
          case "resize":
            return setWidth(drag.width);
          case "collapse":
            setExpandedForKey(taskId, false);
            return setWidth(drag.width);
          case "close":
            closed.current = true;
            return openRightPanelSide(null, taskId);
          case "reopen":
            closed.current = false;
            openRightPanelSide(start.current.side, taskId);
            return setWidth(drag.width);
        }
      }}
      onDragEnd={() => {
        if (closed.current) {
          useRightPanelStore.getState().setWidth(start.current.width);
        }
      }}
    />
  );
}
