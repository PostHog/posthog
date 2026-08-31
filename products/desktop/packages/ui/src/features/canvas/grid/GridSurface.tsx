import { SquaresFourIcon } from "@phosphor-icons/react";
import type {
  GridDefinition,
  GridPlacement,
} from "@posthog/core/canvas/gridLayoutSchemas";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useCallback, useEffect, useRef, useState } from "react";
import { GridCardChrome } from "./GridCardChrome";
import { GridPlacementTile } from "./GridPlacementTile";
import {
  collides,
  type GridRect,
  rectFromCells,
  surfaceRows,
} from "./gridGeometry";
import type { PlacementActions } from "./placementActions";
import { type GridDragOutcome, useGridDrag } from "./useGridDrag";

// Outer radius of a lattice dot's fade (the gradient's transparent stop).
const DOT_FADE_RADIUS = 4;

function gridItemStyle(rect: GridRect): React.CSSProperties {
  return {
    gridColumn: `${rect.x + 1} / span ${rect.w}`,
    gridRow: `${rect.y + 1} / span ${rect.h}`,
  };
}

// Where the how-to tile sits on an empty grid: centered, wide enough to read,
// one row down so it looks placed rather than docked to the top edge.
function emptyHintRect(columns: number): GridRect {
  const w = Math.min(4, columns);
  return { x: Math.floor((columns - w) / 2), y: 1, w, h: 3 };
}

// The dot lattice needs the surface's real pixel width: columns are fractional
// (1fr), so corner positions can't be expressed in pure CSS background math.
function useMeasuredWidth(element: HTMLDivElement | null): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    setWidth(element.clientWidth);
    return () => observer.disconnect();
  }, [element]);
  return width;
}

/**
 * The drawable grid itself: the cards, the lattice they snap to, and the
 * pointer state machine that draws, moves and resizes them. Everything here
 * needs the surface's own measured geometry, so it stays out of the view that
 * owns the canvas's data.
 */
export function GridSurface({
  grid,
  placements,
  interactive,
  patching,
  actions,
  onDragComplete,
}: {
  grid: GridDefinition;
  placements: GridPlacement[];
  interactive: boolean;
  patching: boolean;
  actions: PlacementActions;
  onDragComplete: (outcome: GridDragOutcome) => void;
}) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  // The surface mounts only after loading, so a plain ref never retriggers the
  // measurement effect; a state-backed element does.
  const [surfaceEl, setSurfaceEl] = useState<HTMLDivElement | null>(null);
  const setSurfaceRef = useCallback((el: HTMLDivElement | null) => {
    surfaceRef.current = el;
    setSurfaceEl(el);
  }, []);
  const surfaceWidth = useMeasuredWidth(surfaceEl);

  const {
    drag,
    hover,
    onPointerLeave,
    onSurfacePointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    startMove,
    startResize,
  } = useGridDrag({
    surfaceRef,
    grid,
    interactive,
    onComplete: onDragComplete,
  });

  // Cell pitch in px: cell size plus one gap. Vertical pitch is fixed by the
  // layout; horizontal comes from the measured surface width (1fr columns).
  const pitchX = (surfaceWidth + grid.gap) / grid.columns;
  const pitchY = grid.rowHeight + grid.gap;
  // A cell already under a tile is not free to draw on, so it stays unlit.
  const hoveredRect = hover && rectFromCells(hover, hover);
  const hoveredCell =
    hoveredRect && !collides(hoveredRect, placements) ? hoveredRect : null;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div
        ref={setSurfaceRef}
        className="relative grid"
        style={{
          gridTemplateColumns: `repeat(${grid.columns}, minmax(0, 1fr))`,
          gridAutoRows: `${grid.rowHeight}px`,
          gap: `${grid.gap}px`,
          // Fill the viewport even when the content needs fewer rows, so the
          // whole visible page is drawable (and dotted) rather than a strip.
          minHeight: `max(100%, ${surfaceRows(placements) * pitchY}px)`,
          cursor: interactive ? "crosshair" : undefined,
        }}
        onPointerDown={onSurfacePointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onPointerLeave={onPointerLeave}
        onLostPointerCapture={onPointerCancel}
      >
        {interactive && surfaceWidth > 0 ? (
          // Edit mode reveals the lattice: a soft dot (the fade to transparent
          // is the blur) on each cell corner, where tiles snap and drawing
          // starts, gently pulsing to invite a drag. The overlay's top edge
          // starts at the first interior corner row so no clipped dots hug the
          // top of the page.
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 animate-pulse opacity-60"
            style={{
              top: pitchY - grid.gap / 2 - DOT_FADE_RADIUS,
              backgroundImage:
                "radial-gradient(circle, var(--gray-7) 1px, transparent 4px)",
              backgroundSize: `${pitchX}px ${pitchY}px`,
              backgroundPosition: `${pitchX / 2 - grid.gap / 2}px ${DOT_FADE_RADIUS - pitchY / 2}px`,
            }}
          />
        ) : null}
        {hoveredCell ? (
          // The cell a click would fill, so the empty surface says it is
          // drawable before the pointer goes down.
          <div
            aria-hidden
            className="pointer-events-none rounded-(--radius-3) bg-fill-hover"
            style={gridItemStyle(hoveredCell)}
          />
        ) : null}
        {placements.length === 0 && !drag ? (
          <EmptyGridHint grid={grid} interactive={interactive} />
        ) : null}
        {placements.map((placement) => {
          const dragged =
            drag && drag.kind !== "draw" && drag.placementId === placement.id
              ? drag.rect
              : placement;
          return (
            <div
              key={placement.id}
              className="group relative overflow-hidden rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid)"
              style={gridItemStyle(dragged)}
            >
              <GridPlacementTile
                placement={placement}
                interactive={interactive}
                patching={patching}
                actions={actions}
              />
              {interactive ? (
                <GridCardChrome
                  placement={placement}
                  patching={patching}
                  actions={actions}
                  onMovePointerDown={startMove(placement)}
                  onResizePointerDown={startResize(placement)}
                />
              ) : null}
            </div>
          );
        })}
        {drag ? (
          <div
            className="pointer-events-none rounded-(--radius-3) border-(--accent-8) border-2 border-dashed bg-(--accent-3) opacity-70"
            style={gridItemStyle(drag.rect)}
          />
        ) : null}
      </div>
    </div>
  );
}

/**
 * How-to placed on the grid as a tile of its own, instead of a full-width
 * overlay that looks like broken chrome. Pointer events pass through so the
 * user can draw right over it.
 */
function EmptyGridHint({
  grid,
  interactive,
}: {
  grid: GridDefinition;
  interactive: boolean;
}) {
  return (
    <div
      className="pointer-events-none flex items-center justify-center rounded-(--radius-3) border border-(--gray-6) border-dashed bg-(--gray-2)"
      style={gridItemStyle(emptyHintRect(grid.columns))}
    >
      <Empty className="border-0 bg-transparent">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SquaresFourIcon size={24} />
          </EmptyMedia>
          <EmptyTitle>
            {interactive ? "Draw your first widget" : "An empty canvas"}
          </EmptyTitle>
          <EmptyDescription>
            {interactive
              ? "Click and drag on the dotted grid to draw a box, then describe what should go there."
              : "Select Edit to draw your first widget."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>
  );
}
