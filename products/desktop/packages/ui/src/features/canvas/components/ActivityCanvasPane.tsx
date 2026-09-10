import { CaretDownIcon } from "@phosphor-icons/react";
import { publishedCanvasBuild } from "@posthog/core/canvas/canvasBuildSchemas";
import type { CanvasNavIntent } from "@posthog/core/canvas/freeformSchemas";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Text,
} from "@posthog/quill";
import type { CanvasCapabilities } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { createActivityCanvasDataRequest } from "@posthog/ui/features/canvas/freeform/activityCanvasDataRequest";
import { BuiltCanvas } from "@posthog/ui/features/canvas/freeform/BuiltCanvas";
import { usePinnedArtifact } from "@posthog/ui/features/canvas/freeform/usePinnedArtifact";
import { useActivityFeedSnapshot } from "@posthog/ui/features/canvas/hooks/useActivityFeedSnapshot";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityCanvasStore } from "@posthog/ui/features/canvas/stores/activityCanvasStore";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import {
  navigateToChannelDashboard,
  navigateToChannelTask,
} from "@posthog/ui/router/navigationBridge";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

/** A canvas the Activity page can be drawn with. */
interface ActivityCanvasOption {
  id: string;
  name: string;
  channelId: string;
}

export function ActivityCanvasMenu({
  canvases,
  selectedId,
  onSelect,
}: {
  canvases: ActivityCanvasOption[];
  selectedId: string | null;
  onSelect: (canvasId: string | null) => void;
}) {
  return (
    <>
      {canvases.map((canvas) => (
        <DropdownMenuItem
          key={canvas.id}
          data-selected={canvas.id === selectedId || undefined}
          onClick={() => onSelect(canvas.id)}
        >
          {canvas.name}
        </DropdownMenuItem>
      ))}
      {selectedId && canvases.length > 0 && <DropdownMenuSeparator />}
      {selectedId && (
        <DropdownMenuItem onClick={() => onSelect(null)}>
          Show the built-in feed
        </DropdownMenuItem>
      )}
    </>
  );
}

/**
 * Where a row goes when the canvas asks to open it. A feed crosses spaces, so
 * the destination's own space is resolved from the same data the canvas was
 * given, rather than from the space the canvas itself lives in.
 */
function useActivityCanvasNavigation(
  canvases: ActivityCanvasOption[],
): (intent: CanvasNavIntent) => void {
  const { items } = useTaskActivity();
  const taskSpaces = useMemo(
    () =>
      new Map(
        items.flatMap((item) =>
          item.channelId ? [[item.taskId, item.channelId] as const] : [],
        ),
      ),
    [items],
  );
  const canvasSpaces = useMemo(
    () => new Map(canvases.map((canvas) => [canvas.id, canvas.channelId])),
    [canvases],
  );

  return useCallback(
    (intent: CanvasNavIntent) => {
      switch (intent.target) {
        case "task": {
          const channelId = taskSpaces.get(intent.taskId);
          if (channelId) navigateToChannelTask(channelId, intent.taskId);
          break;
        }
        case "canvas": {
          const channelId = canvasSpaces.get(intent.dashboardId);
          if (channelId) {
            navigateToChannelDashboard(channelId, intent.dashboardId);
          }
          break;
        }
        case "new-task":
          openTaskInput({});
          break;
        // A feed does not create canvases, and connecting a provider belongs to
        // the canvas's own space, which this page is not in.
        default:
          break;
      }
    },
    [canvasSpaces, taskSpaces],
  );
}

function ActivityCanvasFrame({
  canvasId,
  onNavigate,
}: {
  canvasId: string;
  onNavigate: (intent: CanvasNavIntent) => void;
}) {
  const queryClient = useQueryClient();
  const readFeed = useActivityFeedSnapshot();
  const { lifecycle, isError, dataUpdatedAt, refetch } =
    useCanvasBuilds(canvasId);
  const publishedBuild = useMemo(
    () => (lifecycle ? publishedCanvasBuild(lifecycle) : null),
    [lifecycle],
  );
  const { artifact, refreshKey, onReady } = usePinnedArtifact({
    dashboardId: canvasId,
    publishedBuild,
    lifecycle,
    mintedAt: dataUpdatedAt,
    suspended: false,
  });

  const onDataRequest = useMemo(
    () =>
      createActivityCanvasDataRequest({
        canvasId,
        sourceVersionId: publishedBuild?.sourceVersionId,
        readFeed,
        queryClient,
      }),
    [canvasId, publishedBuild?.sourceVersionId, queryClient, readFeed],
  );

  const capabilities = publishedBuild?.manifest
    ? ((publishedBuild.manifest as { capabilities?: CanvasCapabilities })
        .capabilities ?? undefined)
    : undefined;

  if (!artifact) {
    const newestBuild = lifecycle?.builds[0];
    const buildDead =
      lifecycle &&
      !publishedBuild &&
      (!newestBuild || newestBuild.buildStatus === "failed");
    if (buildDead || (isError && !lifecycle)) {
      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 overflow-hidden p-3 text-center">
          <Text size="sm">This canvas isn't ready to draw yet.</Text>
          <Text size="xs" variant="muted">
            Open it in its space to publish a working version, then come back.
          </Text>
          <Button variant="outline" size="sm" onClick={refetch}>
            Retry
          </Button>
        </div>
      );
    }
    return <LoadingState />;
  }

  return (
    <BuiltCanvas
      key={`${artifact.buildId}:${refreshKey}`}
      artifactUrl={artifact.url}
      capabilities={capabilities}
      onDataRequest={onDataRequest}
      onNavigate={onNavigate}
      onReady={onReady}
      onRendered={onReady}
    />
  );
}

/** Every canvas a person can draw their Activity page with. */
export function useActivityCanvasOptions(): ActivityCanvasOption[] {
  const { dashboards } = useAllCanvases();
  return useMemo(
    () =>
      dashboards
        .filter((record) => record.kind === "freeform")
        .map((record) => ({
          id: record.id,
          name: record.name,
          channelId: record.channelId,
        })),
    [dashboards],
  );
}

/** Picks the activity canvas, and reports the pick. */
export function useSelectActivityCanvas(): (canvasId: string | null) => void {
  const setCanvasId = useActivityCanvasStore((state) => state.setCanvasId);
  return useCallback(
    (canvasId: string | null) => {
      setCanvasId(canvasId);
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "activity_canvas_change",
        surface: "activity",
      });
    },
    [setCanvasId],
  );
}

/**
 * The Activity page, drawn by a canvas the person picked, in place of the
 * built-in feed.
 */
export function ActivityCanvasPane({ canvasId }: { canvasId: string }) {
  const canvases = useActivityCanvasOptions();
  const selectCanvas = useSelectActivityCanvas();
  const onNavigate = useActivityCanvasNavigation(canvases);
  const selected = canvases.find((canvas) => canvas.id === canvasId) ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-b-(--gray-6) pr-2 pl-3">
        <span className="min-w-0 flex-1 truncate font-medium text-[13px]">
          {selected?.name ?? "Activity canvas"}
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="default"
                size="icon-sm"
                aria-label="Change activity canvas"
              >
                <CaretDownIcon size={14} />
              </Button>
            }
          />
          <DropdownMenuContent align="end" className="min-w-56">
            <ActivityCanvasMenu
              canvases={canvases}
              selectedId={canvasId}
              onSelect={selectCanvas}
            />
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="min-h-0 flex-1">
        <ActivityCanvasFrame canvasId={canvasId} onNavigate={onNavigate} />
      </div>
    </div>
  );
}
