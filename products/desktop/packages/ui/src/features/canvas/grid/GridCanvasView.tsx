import { SidebarSimpleIcon } from "@phosphor-icons/react";
import type {
  GridPlacement,
  LayoutOperation,
} from "@posthog/core/canvas/gridLayoutSchemas";
import { Button, Spinner, Text } from "@posthog/quill";
import { canvasCommentTaskId } from "@posthog/ui/features/canvas/freeform/canvasCommentTask";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  useCanvasVersions,
  useDashboard,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useCallback, useMemo, useState } from "react";
import { GridChatPanel, type GridChatTarget } from "./GridChatPanel";
import { GridSurface } from "./GridSurface";
import { collides } from "./gridGeometry";
import type { PlacementActions } from "./placementActions";
import type { GridDragOutcome } from "./useGridDrag";
import { useGridLayout, usePatchLayout } from "./useGridLayout";

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

  const actions = useMemo<PlacementActions>(
    () => ({ describe, reset, remove, discuss }),
    [describe, reset, remove, discuss],
  );

  if (isLoading || !layout || !placements || !dashboard) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
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
        <GridSurface
          grid={layout.grid}
          placements={placements}
          interactive={interactive}
          patching={isPatching}
          actions={actions}
          onDragComplete={onDragComplete}
        />
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
