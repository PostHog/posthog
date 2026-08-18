import { SquaresFourIcon } from "@phosphor-icons/react";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type {
  ComponentSize,
  GridPlacement,
} from "@posthog/core/canvas/gridLayoutSchemas";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { useDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { toast } from "@posthog/ui/primitives/toast";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  GridPlacementTile,
  type PlacementTileActions,
} from "./GridPlacementTile";
import {
  clampRectToContract,
  collides,
  type GridRect,
  surfaceRows,
} from "./gridGeometry";
import { type GridDragOutcome, useGridDrag } from "./useGridDrag";
import {
  useComponentStore,
  useGridLayout,
  usePatchLayout,
} from "./useGridLayout";

const DEFAULT_GRID = { columns: 6, rowHeight: 96, gap: 8 };

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
 * A grid canvas: a composition of component widgets on a fixed-column grid.
 * Viewing renders each live placement's built artifact in its own sandboxed
 * frame; edit mode adds draw-to-create (drag an empty area, describe the box),
 * move (drag a tile), and resize (drag the corner handle). Every edit is a
 * surgical, version-guarded layout patch, so a user and an agent editing the
 * same canvas conflict loudly instead of overwriting each other.
 */
export function GridCanvasView({
  canvasId,
  interactive,
}: {
  canvasId: string;
  interactive: boolean;
}) {
  const { dashboard } = useDashboard(canvasId);
  const { layout, currentVersionId, isLoading } = useGridLayout(canvasId);
  const { patch } = usePatchLayout(canvasId);
  const { generate } = useGenerateFreeformCanvas({
    channelId: dashboard?.channelId ?? "",
    channelName: "",
  });

  const surfaceRef = useRef<HTMLDivElement>(null);
  // The surface mounts only after loading, so a plain ref never retriggers the
  // measurement effect; a state-backed element does.
  const [surfaceEl, setSurfaceEl] = useState<HTMLDivElement | null>(null);
  const setSurfaceRef = useCallback((el: HTMLDivElement | null) => {
    surfaceRef.current = el;
    setSurfaceEl(el);
  }, []);
  const surfaceWidth = useMeasuredWidth(surfaceEl);
  const placements = layout?.placements;
  const columns = layout?.grid.columns ?? DEFAULT_GRID.columns;

  // Size contracts of the placed components, for snapping edits into range
  // before the server would reject them. Fetched only while editing a grid
  // that has live placements; an entry missing (still loading, or a stale
  // reference) just skips the snap and lets the server answer.
  const hasLivePlacements = !!placements?.some(
    (candidate) => candidate.status === "live" && candidate.component,
  );
  const { components: storeComponents } = useComponentStore("", {
    enabled: interactive && hasLivePlacements,
  });
  const contractByComponent = useMemo(() => {
    const map = new Map<string, ComponentSize>();
    for (const component of storeComponents) {
      if (component.componentMeta?.size) {
        map.set(component.id, component.componentMeta.size);
      }
    }
    return map;
  }, [storeComponents]);

  const onDragComplete = useCallback(
    (outcome: GridDragOutcome) => {
      if (!placements) return;
      if (outcome.kind === "draw") {
        if (collides(outcome.rect, placements)) return;
        void patch(
          [
            {
              op: "add_placement",
              placement: {
                id: `p-${crypto.randomUUID().slice(0, 8)}`,
                status: "pending",
                ...outcome.rect,
              },
            },
          ],
          currentVersionId,
        );
        return;
      }
      let { rect } = outcome;
      const { origin, placementId } = outcome;
      if (!origin || !placementId) return;
      if (outcome.kind === "resize") {
        const target = placements.find(
          (candidate) => candidate.id === placementId,
        );
        const size = target?.component
          ? contractByComponent.get(target.component)
          : undefined;
        if (size) rect = clampRectToContract(rect, size, columns);
      }
      const moved =
        rect.x !== origin.x ||
        rect.y !== origin.y ||
        rect.w !== origin.w ||
        rect.h !== origin.h;
      if (!moved || collides(rect, placements, placementId)) return;
      void patch(
        [{ op: "update_placement", id: placementId, changes: rect }],
        currentVersionId,
      );
    },
    [placements, patch, currentVersionId, contractByComponent, columns],
  );

  const {
    drag,
    onSurfacePointerDown,
    onPointerMove,
    onPointerUp,
    startMove,
    startResize,
  } = useGridDrag({
    surfaceRef,
    grid: layout?.grid ?? DEFAULT_GRID,
    interactive,
    onComplete: onDragComplete,
  });

  const describe = useCallback(
    async (placement: GridPlacement, prompt: string) => {
      if (!dashboard) return;
      // Flip the tile to its generating state before dispatching the task —
      // task creation takes seconds, and a silent describe box reads as broken.
      const staged = await patch(
        [
          {
            op: "update_placement",
            id: placement.id,
            changes: { status: "generating", prompt },
          },
        ],
        currentVersionId,
        prompt,
      );
      if (!staged) return;
      const taskId = await generate({
        dashboardId: canvasId,
        name: dashboard.name,
        instruction: prompt,
        placement: {
          placementId: placement.id,
          w: placement.w,
          h: placement.h,
        },
      });
      await patch(
        [
          {
            op: "update_placement",
            id: placement.id,
            // Dispatch failed (already toasted): back to pending so the box
            // offers the prompt again instead of spinning forever.
            changes: taskId
              ? { generationTaskId: taskId }
              : { status: "pending" },
          },
        ],
        staged.currentVersionId ?? null,
      );
    },
    [dashboard, generate, patch, canvasId, currentVersionId],
  );

  const place = useCallback(
    (placement: GridPlacement, component: DashboardRecord) => {
      // Snap the drawn box into the component's size contract; the server
      // rejects a live placement outside it. Growing can collide with a
      // neighbor, which is the user's call to resolve, not a patch to send.
      const size = component.componentMeta?.size;
      const target = size
        ? clampRectToContract(placement, size, columns)
        : placement;
      if (placements && collides(target, placements, placement.id) && size) {
        toast.error("Not enough room for this component", {
          description: `It needs at least ${size.minW}x${size.minH} cells. Clear the space around the box or draw a bigger one.`,
        });
        return;
      }
      void patch(
        [
          {
            op: "update_placement",
            id: placement.id,
            changes: {
              status: "live",
              component: component.id,
              config: {},
              x: target.x,
              y: target.y,
              w: target.w,
              h: target.h,
            },
          },
        ],
        currentVersionId,
        `Place ${component.name}`,
      );
    },
    [patch, currentVersionId, placements, columns],
  );

  const reset = useCallback(
    (placement: GridPlacement) => {
      // Back to the describe box with the prompt intact; the stale task id is
      // ignored outside the generating state and overwritten on re-dispatch.
      void patch(
        [
          {
            op: "update_placement",
            id: placement.id,
            changes: { status: "pending" },
          },
        ],
        currentVersionId,
      );
    },
    [patch, currentVersionId],
  );

  const remove = useCallback(
    (placement: GridPlacement) => {
      void patch(
        [{ op: "remove_placement", id: placement.id }],
        currentVersionId,
      );
    },
    [patch, currentVersionId],
  );

  const actions: PlacementTileActions = { describe, place, reset, remove };

  if (isLoading || !layout || !placements || !dashboard) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  const { grid } = layout;
  // Cell pitch in px: cell size plus one gap. Vertical pitch is fixed by the
  // layout; horizontal comes from the measured surface width (1fr columns).
  const pitchX = (surfaceWidth + grid.gap) / grid.columns;
  const pitchY = grid.rowHeight + grid.gap;

  return (
    <div className="h-full overflow-y-auto p-4">
      {/* biome-ignore lint/a11y/noStaticElementInteractions: the surface is a drawing target; tiles inside stay keyboard-reachable. */}
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
        {placements.length === 0 && !drag ? (
          // How-to placed on the grid as a tile of its own, instead of a
          // full-width overlay that looks like broken chrome. Pointer events
          // pass through so the user can draw right over it.
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
                    ? "Click and drag on the dotted grid to draw a box, then describe what should go there or pick a component from the store."
                    : "Select Edit to draw your first widget."}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          </div>
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
              {interactive ? (
                <div
                  className="absolute inset-x-0 top-0 z-10 h-5 cursor-move bg-(--gray-3) opacity-0 transition-opacity group-hover:opacity-100"
                  onPointerDown={startMove(placement)}
                />
              ) : null}
              <GridPlacementTile
                placement={placement}
                channelId={dashboard.channelId}
                interactive={interactive}
                actions={actions}
              />
              {interactive ? (
                <div
                  className="absolute right-0 bottom-0 z-10 h-4 w-4 cursor-nwse-resize bg-(--gray-6) opacity-0 transition-opacity group-hover:opacity-100"
                  onPointerDown={startResize(placement)}
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
