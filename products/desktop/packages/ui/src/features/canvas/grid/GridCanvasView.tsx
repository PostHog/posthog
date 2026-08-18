import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { useDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { useCallback, useRef } from "react";
import {
  GridPlacementTile,
  type PlacementTileActions,
} from "./GridPlacementTile";
import { collides, type GridRect, surfaceRows } from "./gridGeometry";
import { type GridDragOutcome, useGridDrag } from "./useGridDrag";
import { useGridLayout, usePatchLayout } from "./useGridLayout";

const DEFAULT_GRID = { columns: 6, rowHeight: 96, gap: 8 };

function gridItemStyle(rect: GridRect): React.CSSProperties {
  return {
    gridColumn: `${rect.x + 1} / span ${rect.w}`,
    gridRow: `${rect.y + 1} / span ${rect.h}`,
  };
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
  const placements = layout?.placements;

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
      const { rect, origin, placementId } = outcome;
      if (!origin || !placementId) return;
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
    [placements, patch, currentVersionId],
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
            changes: taskId
              ? { status: "generating", prompt, generationTaskId: taskId }
              : { status: "pending", prompt },
          },
        ],
        currentVersionId,
        prompt,
      );
    },
    [dashboard, generate, patch, canvasId, currentVersionId],
  );

  const place = useCallback(
    (placement: GridPlacement, component: DashboardRecord) => {
      void patch(
        [
          {
            op: "update_placement",
            id: placement.id,
            changes: { status: "live", component: component.id, config: {} },
          },
        ],
        currentVersionId,
        `Place ${component.name}`,
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

  const actions: PlacementTileActions = { describe, place, remove };

  if (isLoading || !layout || !placements || !dashboard) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  const { grid } = layout;

  return (
    <div className="h-full overflow-y-auto p-4">
      {placements.length === 0 && !drag ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <Empty>
            <EmptyHeader>
              <EmptyTitle>
                {interactive ? "Draw your first widget" : "An empty canvas"}
              </EmptyTitle>
              <EmptyDescription>
                {interactive
                  ? "Drag anywhere on the grid, then describe what should live there."
                  : "Nothing has been placed on this canvas yet."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        </div>
      ) : null}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: the surface is a drawing target; tiles inside stay keyboard-reachable. */}
      <div
        ref={surfaceRef}
        className="relative grid min-h-full"
        style={{
          gridTemplateColumns: `repeat(${grid.columns}, minmax(0, 1fr))`,
          gridAutoRows: `${grid.rowHeight}px`,
          gap: `${grid.gap}px`,
          minHeight: surfaceRows(placements) * (grid.rowHeight + grid.gap),
          cursor: interactive ? "crosshair" : undefined,
        }}
        onPointerDown={onSurfacePointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
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
