import type {
  GridDefinition,
  GridPlacement,
} from "@posthog/core/canvas/gridLayoutSchemas";
import { type RefObject, useState } from "react";
import {
  cellFromPoint,
  clampRect,
  type GridCell,
  type GridRect,
  rectFromCells,
  sameCell,
} from "./gridGeometry";

export type GridDragState =
  | { kind: "draw"; anchor: GridCell; rect: GridRect }
  | {
      kind: "move";
      placementId: string;
      grabbed: GridCell;
      origin: GridRect;
      rect: GridRect;
    }
  | { kind: "resize"; placementId: string; origin: GridRect; rect: GridRect };

export interface GridDragOutcome {
  kind: GridDragState["kind"];
  rect: GridRect;
  placementId?: string;
  origin?: GridRect;
}

/**
 * The pointer state machine behind the grid editor: draw a new box on the
 * empty surface, move a tile, or resize one from its corner handle. Cells are
 * snapped as the pointer moves (move/resize rects stay clamped to the grid);
 * the caller decides what a completed drag means.
 */
export function useGridDrag({
  surfaceRef,
  grid,
  interactive,
  onComplete,
}: {
  surfaceRef: RefObject<HTMLDivElement | null>;
  grid: GridDefinition;
  interactive: boolean;
  onComplete: (outcome: GridDragOutcome) => void;
}) {
  const [drag, setDrag] = useState<GridDragState | null>(null);
  // The empty cell under a resting pointer, so the surface can show where a
  // click would put a box. Only the surface itself reports one: a tile handles
  // its own presses, and hovering it is not an offer to draw.
  const [hover, setHover] = useState<GridCell | null>(null);

  const cellAt = (event: React.PointerEvent) => {
    const surface = surfaceRef.current?.getBoundingClientRect();
    if (!surface) return { col: 0, row: 0 };
    return cellFromPoint(event.clientX, event.clientY, surface, grid);
  };

  const capture = (event: React.PointerEvent) =>
    surfaceRef.current?.setPointerCapture(event.pointerId);

  const onSurfacePointerDown = (event: React.PointerEvent) => {
    if (!interactive || event.button !== 0) return;
    // Only a press on the empty surface starts a draw; tiles own their presses.
    if (event.target !== surfaceRef.current) return;
    const anchor = cellAt(event);
    capture(event);
    setHover(null);
    setDrag({ kind: "draw", anchor, rect: rectFromCells(anchor, anchor) });
  };

  const startMove =
    (placement: GridPlacement) => (event: React.PointerEvent) => {
      if (!interactive || event.button !== 0) return;
      event.stopPropagation();
      capture(event);
      setHover(null);
      setDrag({
        kind: "move",
        placementId: placement.id,
        grabbed: cellAt(event),
        origin: placement,
        rect: {
          x: placement.x,
          y: placement.y,
          w: placement.w,
          h: placement.h,
        },
      });
    };

  const startResize =
    (placement: GridPlacement) => (event: React.PointerEvent) => {
      if (!interactive || event.button !== 0) return;
      event.stopPropagation();
      capture(event);
      setHover(null);
      setDrag({
        kind: "resize",
        placementId: placement.id,
        origin: placement,
        rect: {
          x: placement.x,
          y: placement.y,
          w: placement.w,
          h: placement.h,
        },
      });
    };

  const onPointerMove = (event: React.PointerEvent) => {
    if (!drag) {
      const cell =
        interactive && event.target === surfaceRef.current
          ? cellAt(event)
          : null;
      // Every pointer move crosses this, and the surface renders a widget per
      // tile — so hold the same cell rather than re-rendering the canvas at
      // pointer rate.
      setHover((current) => (sameCell(current, cell) ? current : cell));
      return;
    }
    const cell = cellAt(event);
    if (drag.kind === "draw") {
      setDrag({ ...drag, rect: rectFromCells(drag.anchor, cell) });
    } else if (drag.kind === "move") {
      const rect = clampRect(
        {
          ...drag.origin,
          x: drag.origin.x + (cell.col - drag.grabbed.col),
          y: drag.origin.y + (cell.row - drag.grabbed.row),
        },
        grid.columns,
      );
      setDrag({ ...drag, rect });
    } else {
      const rect = clampRect(
        {
          ...drag.origin,
          w: cell.col - drag.origin.x + 1,
          h: cell.row - drag.origin.y + 1,
        },
        grid.columns,
      );
      setDrag({ ...drag, rect });
    }
  };

  const onPointerUp = () => {
    if (!drag) return;
    setDrag(null);
    onComplete({
      kind: drag.kind,
      // Move/resize rects are clamped on every pointer move; only a drawn
      // rect still needs it.
      rect:
        drag.kind === "draw" ? clampRect(drag.rect, grid.columns) : drag.rect,
      placementId: drag.kind === "draw" ? undefined : drag.placementId,
      origin: drag.kind === "draw" ? undefined : drag.origin,
    });
  };

  // A preempted pointer (a trackpad or touch gesture the browser cancels, or
  // lost capture) drops the gesture WITHOUT committing it — clearing drag snaps
  // the tile back to its real position. Skipping this leaves a stale drag that
  // tracks the cursor with no button held and persists an unmade edit on the
  // next click.
  const onPointerCancel = () => {
    setDrag(null);
  };

  const onPointerLeave = () => {
    setHover(null);
  };

  return {
    drag,
    // Derived rather than reset: a hover left behind by the pointer resting on
    // the surface when edit mode ends would otherwise paint a cell the canvas
    // no longer lets you fill.
    hover: interactive ? hover : null,
    onPointerLeave,
    onSurfacePointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    startMove,
    startResize,
  };
}
