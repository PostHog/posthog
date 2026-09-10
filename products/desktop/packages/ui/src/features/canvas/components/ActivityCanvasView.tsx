import { CaretDownIcon, SquaresFourIcon } from "@phosphor-icons/react";
import { publishedCanvasBuild } from "@posthog/core/canvas/canvasBuildSchemas";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Text,
} from "@posthog/quill";
import type { CanvasCapabilities } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task, TaskThreadMessage } from "@posthog/shared/domain-types";
import { createActivityCanvasDataRequest } from "@posthog/ui/features/canvas/freeform/activityCanvasDataRequest";
import { BuiltCanvas } from "@posthog/ui/features/canvas/freeform/BuiltCanvas";
import { usePinnedArtifact } from "@posthog/ui/features/canvas/freeform/usePinnedArtifact";
import { useCanvasBuilds } from "@posthog/ui/features/canvas/hooks/useCanvasBuilds";
import { useDashboards } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useTaskActivitySnapshot } from "@posthog/ui/features/canvas/hooks/useTaskActivitySnapshot";
import { useActivityCanvasStore } from "@posthog/ui/features/canvas/stores/activityCanvasStore";
import type { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useCallback, useMemo } from "react";

type ConversationItem = ReturnType<
  typeof buildConversationItems
>["items"][number];

type ReadActivity = (limit?: number) => unknown;

/** A canvas the panel can draw its activity with. */
interface ActivityCanvasOption {
  id: string;
  name: string;
}

function CanvasPicker({
  canvases,
  selectedId,
  onSelect,
  trigger,
}: {
  canvases: ActivityCanvasOption[];
  selectedId: string | null;
  onSelect: (canvasId: string | null) => void;
  trigger: ReactElement;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={trigger} />
      <DropdownMenuContent align="end">
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
            Show the built-in timeline
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * The chosen canvas, in the panel. Data requests are scoped to that canvas, the
 * way a grid widget's are, apart from `taskActivity`: the host answers that one
 * for the task whose panel the canvas is mounted in, so a canvas can never read
 * a task its viewer did not open.
 */
function ActivityCanvasFrame({
  canvasId,
  readActivity,
}: {
  canvasId: string;
  readActivity: ReadActivity;
}) {
  const queryClient = useQueryClient();
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
        readActivity,
        queryClient,
      }),
    [canvasId, publishedBuild?.sourceVersionId, queryClient, readActivity],
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
      onReady={onReady}
      onRendered={onReady}
    />
  );
}

/**
 * The activity panel's Canvas tab: this person's own canvas drawing the task's
 * activity, in place of the built-in timeline.
 */
export function ActivityCanvasView({
  task,
  messages,
  conversationItems,
}: {
  task: Task;
  messages: TaskThreadMessage[];
  conversationItems: ConversationItem[];
}) {
  const canvasId = useActivityCanvasStore((state) => state.canvasId);
  const setCanvasId = useActivityCanvasStore((state) => state.setCanvasId);
  const readActivity = useTaskActivitySnapshot({
    task,
    messages,
    conversationItems,
  });
  const { dashboards } = useDashboards(task.channel ?? undefined);
  const canvases: ActivityCanvasOption[] = useMemo(
    () => dashboards.map((record) => ({ id: record.id, name: record.name })),
    [dashboards],
  );
  const selected = canvases.find((canvas) => canvas.id === canvasId) ?? null;

  const onSelect = useCallback(
    (next: string | null) => {
      setCanvasId(next);
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "activity_canvas_change",
        surface: "activity_panel",
        task_id: task.id,
        channel_id: task.channel ?? undefined,
      });
    },
    [setCanvasId, task.channel, task.id],
  );

  if (!canvasId) {
    return (
      <div className="flex h-full items-center justify-center p-3">
        <Empty className="border-0">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <SquaresFourIcon />
            </EmptyMedia>
            <EmptyTitle>Draw activity with a canvas</EmptyTitle>
            <EmptyDescription>
              {canvases.length
                ? "Pick a canvas from this space. It reads the same activity the built-in timeline draws, and shows it your way."
                : "This space has no canvases yet. Ask the agent for one that reads this task's activity, then pick it here."}
            </EmptyDescription>
          </EmptyHeader>
          {canvases.length > 0 && (
            <EmptyContent>
              <CanvasPicker
                canvases={canvases}
                selectedId={null}
                onSelect={onSelect}
                trigger={<Button variant="primary">Choose a canvas…</Button>}
              />
            </EmptyContent>
          )}
        </Empty>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-b-(--gray-6) pr-1 pl-2">
        <span className="min-w-0 flex-1 truncate text-[13px]">
          {selected?.name ?? "Activity canvas"}
        </span>
        <CanvasPicker
          canvases={canvases}
          selectedId={canvasId}
          onSelect={onSelect}
          trigger={
            <Button
              variant="default"
              size="icon-sm"
              aria-label="Change activity canvas"
            >
              <CaretDownIcon size={14} />
            </Button>
          }
        />
      </div>
      <div className="min-h-0 flex-1">
        <ActivityCanvasFrame canvasId={canvasId} readActivity={readActivity} />
      </div>
    </div>
  );
}
