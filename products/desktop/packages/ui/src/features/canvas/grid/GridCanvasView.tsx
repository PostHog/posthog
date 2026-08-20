import {
  ChatCircleIcon,
  SidebarSimpleIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import type {
  GridPlacement,
  LayoutOperation,
} from "@posthog/core/canvas/gridLayoutSchemas";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import { canvasCommentTaskId } from "@posthog/ui/features/canvas/freeform/canvasCommentTask";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  useCanvasVersions,
  useDashboard,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GridChatPanel, type GridChatTarget } from "./GridChatPanel";
import {
  GridPlacementTile,
  type PlacementTileActions,
} from "./GridPlacementTile";
import {
  collides,
  type GridRect,
  rectFromCells,
  surfaceRows,
} from "./gridGeometry";
import { type GridDragOutcome, useGridDrag } from "./useGridDrag";
import { useGridLayout, usePatchLayout } from "./useGridLayout";

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
  const { patch, isPatching } = usePatchLayout(canvasId);
  // Resolve the channel's display name from the shared channels query, like the
  // freeform view does, so a started run names its channel in the agent prompt
  // (an empty name drops the whole channel-context instruction).
  const channelId = dashboard?.channelId ?? "";
  const { channels } = useChannels();
  const channelName = useMemo(
    () => channels.find((channel) => channel.id === channelId)?.name ?? "",
    [channels, channelId],
  );
  const { generate } = useGenerateFreeformCanvas({ channelId, channelName });

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

  // The right-hand dock, sharing the freeform panel's persisted collapse and
  // width so the two canvas kinds feel like one surface. Edit mode opens it
  // on the canvas's own conversation; a widget's chat affordances refocus it.
  const collapsed = useCanvasChatPanelStore((s) => s.collapsed);
  const setCollapsed = useCanvasChatPanelStore((s) => s.setCollapsed);
  const panelWidth = useCanvasChatPanelStore((s) => s.width);
  const setPanelWidth = useCanvasChatPanelStore((s) => s.setWidth);
  // Comments opened from view mode (the breadcrumb's Comments button) hold the
  // dock open without edit mode, exactly like the freeform panel.
  const viewOpen = useCanvasChatPanelStore((s) => s.viewOpen);
  const [isResizingPanel, setIsResizingPanel] = useState(false);
  const [widgetTarget, setWidgetTarget] = useState<GridChatTarget | null>(null);
  // Canvas-wide task started this session, until the record catches up.
  const [startedCanvasTaskId, setStartedCanvasTaskId] = useState<string | null>(
    null,
  );

  // The layout version the grid is on, in the freeform toolbar's vocabulary.
  const { versions } = useCanvasVersions(canvasId);
  const versionText = useMemo(() => {
    if (!currentVersionId || versions.length === 0) return null;
    const index = versions.findIndex(
      (version) => version.id === currentVersionId,
    );
    if (index === -1) return null;
    return `v${versions.length - index}/${versions.length} · Live`;
  }, [versions, currentVersionId]);
  const commentVersionLabel = useCallback(
    (versionId: string) => {
      const index = versions.findIndex((version) => version.id === versionId);
      return index === -1 ? null : `V${versions.length - index}`;
    },
    [versions],
  );

  const onDragComplete = useCallback(
    (outcome: GridDragOutcome) => {
      if (!placements) return;
      if (outcome.kind === "draw") {
        if (collides(outcome.rect, placements)) return;
        void patch([
          {
            op: "add_placement",
            placement: {
              id: `p-${crypto.randomUUID().slice(0, 8)}`,
              status: "pending",
              ...outcome.rect,
            },
          },
        ]);
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
      void patch([{ op: "update_placement", id: placementId, changes: rect }]);
    },
    [placements, patch],
  );

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
      const record: LayoutOperation[] = [
        {
          op: "update_placement",
          id: placement.id,
          // Dispatch failed (already toasted): back to pending so the box
          // offers the prompt again instead of spinning forever.
          changes: taskId
            ? { generationTaskId: taskId }
            : { status: "pending" },
        },
      ];
      // The task is already running and its id is known only here, so losing
      // this write leaves a tile generating forever with nothing to open. The
      // queue rebases after a failure, so one retry clears a lost race.
      if (!(await patch(record))) await patch(record);
    },
    [dashboard, generate, patch, canvasId],
  );

  const reset = useCallback(
    (placement: GridPlacement) => {
      // Back to the describe box with the prompt intact; the stale task id is
      // ignored outside the generating state and overwritten on re-dispatch.
      void patch([
        {
          op: "update_placement",
          id: placement.id,
          changes: { status: "pending" },
        },
      ]);
    },
    [patch],
  );

  const remove = useCallback(
    (placement: GridPlacement) => {
      void patch([{ op: "remove_placement", id: placement.id }]);
    },
    [patch],
  );

  const discuss = useCallback(
    (placement: GridPlacement) => {
      setWidgetTarget({
        taskId: placement.generationTaskId ?? null,
        title: placement.prompt ?? "Widget",
      });
      setCollapsed(false);
    },
    [setCollapsed],
  );

  const actions: PlacementTileActions = {
    describe,
    reset,
    remove,
    discuss,
  };

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
  // A cell already under a tile is not free to draw on, so it stays unlit.
  const hoveredRect = hover && rectFromCells(hover, hover);
  const hoveredCell =
    hoveredRect && !collides(hoveredRect, placements) ? hoveredRect : null;

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        {interactive ? (
          // The freeform canvas's toolbar shape: version info on the left,
          // panel controls on the right, in the bar rather than floating.
          <div className="flex h-10 shrink-0 items-center justify-between border-(--gray-5) border-b px-3">
            <div className="flex items-center gap-1">
              {versionText ? (
                <Text size="sm" className="text-(--gray-9)">
                  {versionText}
                </Text>
              ) : null}
            </div>
            {collapsed && !widgetTarget ? (
              <Button
                variant="default"
                size="icon"
                aria-label="Show chat"
                onClick={() => setCollapsed(false)}
              >
                <SidebarSimpleIcon size={16} />
              </Button>
            ) : null}
          </div>
        ) : null}
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
                      {interactive
                        ? "Draw your first widget"
                        : "An empty canvas"}
                    </EmptyTitle>
                    <EmptyDescription>
                      {interactive
                        ? "Click and drag on the dotted grid to draw a box, then describe what should go there."
                        : "Select Edit to draw your first widget."}
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              </div>
            ) : null}
            {placements.map((placement) => {
              const dragged =
                drag &&
                drag.kind !== "draw" &&
                drag.placementId === placement.id
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
                    interactive={interactive}
                    patching={isPatching}
                    actions={actions}
                  />
                  {interactive && placement.generationTaskId ? (
                    // Opens the widget's own conversation in the side panel so a
                    // broken query or tweak goes straight back to its agent.
                    <Button
                      variant="outline"
                      size="icon"
                      className="absolute top-1 right-1 z-20 opacity-0 transition-opacity group-hover:opacity-100"
                      onPointerDown={(event) => event.stopPropagation()}
                      onClick={() => actions.discuss(placement)}
                    >
                      <ChatCircleIcon size={14} />
                    </Button>
                  ) : null}
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
      </div>
      {interactive || widgetTarget || viewOpen ? (
        <ResizableSidebar
          open={!collapsed || !!widgetTarget}
          width={panelWidth}
          setWidth={setPanelWidth}
          isResizing={isResizingPanel}
          setIsResizing={setIsResizingPanel}
          side="right"
        >
          <GridChatPanel
            target={widgetTarget}
            canvasTaskId={dashboard.generationTaskId ?? startedCanvasTaskId}
            commentTaskId={canvasCommentTaskId(
              dashboard.generationTaskId ?? startedCanvasTaskId,
              versions,
            )}
            canvasVersionId={currentVersionId ?? null}
            commentVersionLabel={commentVersionLabel}
            canvasId={canvasId}
            canvasName={dashboard.name}
            channelId={dashboard.channelId}
            channelName={channelName}
            onBack={() => setWidgetTarget(null)}
            onMinimize={() => {
              setCollapsed(true);
              setWidgetTarget(null);
            }}
            onStarted={setStartedCanvasTaskId}
          />
        </ResizableSidebar>
      ) : null}
    </div>
  );
}
