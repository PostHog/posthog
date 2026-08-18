import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Input,
  Spinner,
  Text,
} from "@posthog/quill";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { taskCardNavigation } from "@posthog/ui/features/canvas/taskCardNavigation";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { ComponentFrame } from "./ComponentFrame";
import { useComponentStore } from "./useGridLayout";

// Poll cadence for the fill task's run status while a tile is generating —
// matches the canvas generation poll elsewhere.
const FILL_TASK_POLL_MS = 5_000;

export interface PlacementTileActions {
  /** Dispatch an agent task to fill this placement with the given ask. */
  describe: (placement: GridPlacement, prompt: string) => Promise<void>;
  /** Fill this placement with an existing store component. */
  place: (placement: GridPlacement, component: DashboardRecord) => void;
  /** Put a stalled placement back to pending so it can be re-described. */
  reset: (placement: GridPlacement) => void;
  /** Remove this placement from the layout. */
  remove: (placement: GridPlacement) => void;
}

/**
 * One placement on the grid, rendered by lifecycle status: a live widget, a
 * drawn box awaiting its description, an agent filling it, or a failed fill
 * offering a retry.
 */
export function GridPlacementTile({
  placement,
  channelId,
  interactive,
  actions,
}: {
  placement: GridPlacement;
  channelId: string;
  interactive: boolean;
  actions: PlacementTileActions;
}) {
  if (placement.status === "live" && placement.component) {
    return <ComponentFrame placement={placement} />;
  }
  if (placement.status === "generating") {
    return (
      <GeneratingTile
        placement={placement}
        channelId={channelId}
        interactive={interactive}
        actions={actions}
      />
    );
  }
  return (
    <DescribeTile
      placement={placement}
      failed={placement.status === "failed"}
      interactive={interactive}
      actions={actions}
    />
  );
}

function GeneratingTile({
  placement,
  channelId,
  interactive,
  actions,
}: {
  placement: GridPlacement;
  channelId: string;
  interactive: boolean;
  actions: PlacementTileActions;
}) {
  const navigate = useNavigate();
  const taskId = placement.generationTaskId ?? null;
  const { data: task } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: !!taskId,
    refetchInterval: FILL_TASK_POLL_MS,
  });
  // The agent owns moving the placement to live or failed. A terminal run
  // with the placement still generating means it never did (crashed, missing
  // skill, gave up) — spinning forever would hide that.
  const stalled =
    !!task?.latest_run && isTerminalStatus(task.latest_run.status);
  // A run blocked on a permission request looks identical to one that's
  // working — from this tile, forever. Surface the wait so the user knows
  // the next move is theirs.
  const runId = useSessionStore((s) =>
    taskId ? s.taskIdIndex[taskId] : undefined,
  );
  const pendingApprovals = useSessionStore((s) =>
    runId ? (s.sessions[runId]?.pendingPermissions?.size ?? 0) : 0,
  );

  const viewTask = taskId ? (
    <Button
      variant="outline"
      size="sm"
      onClick={() => navigate(taskCardNavigation(channelId, taskId))}
    >
      {stalled ? "View task" : "View progress"}
    </Button>
  ) : null;

  if (stalled) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center">
        <Text size="sm" className="line-clamp-2">
          The agent finished without updating this widget.
        </Text>
        <div className="flex items-center gap-1">
          {interactive ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => actions.reset(placement)}
            >
              Try again
            </Button>
          ) : null}
          {viewTask}
        </div>
      </div>
    );
  }

  if (pendingApprovals > 0) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center">
        <Text size="sm" className="line-clamp-2">
          The agent is waiting for your approval.
        </Text>
        <div className="flex items-center gap-1">
          {taskId ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => navigate(taskCardNavigation(channelId, taskId))}
            >
              Review request
            </Button>
          ) : null}
          {interactive ? (
            <Button
              variant="default"
              size="sm"
              onClick={() => actions.remove(placement)}
            >
              Remove
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center">
      <Spinner />
      <Text size="sm" className="line-clamp-2">
        {placement.prompt ?? "Building this widget…"}
      </Text>
      <div className="flex items-center gap-1">
        {viewTask}
        {interactive ? (
          <Button
            variant="default"
            size="sm"
            onClick={() => actions.remove(placement)}
          >
            Remove
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function DescribeTile({
  placement,
  failed,
  interactive,
  actions,
}: {
  placement: GridPlacement;
  failed: boolean;
  interactive: boolean;
  actions: PlacementTileActions;
}) {
  const [prompt, setPrompt] = useState(placement.prompt ?? "");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [storeOpen, setStoreOpen] = useState(false);
  const [storeSearch, setStoreSearch] = useState("");
  // The store query only fires once the picker opens — a grid full of drawn
  // boxes must not fan out one store fetch per tile on mount.
  const { components } = useComponentStore(storeSearch, { enabled: storeOpen });
  const placeable = components.filter(
    (component) => component.componentMeta && component.publishedBuildId,
  );

  if (!interactive) {
    return (
      <div className="flex h-full w-full items-center justify-center p-3">
        <Text size="sm">
          {failed ? "This widget failed to build." : "An empty widget."}
        </Text>
      </div>
    );
  }
  const submit = async () => {
    if (!prompt.trim() || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await actions.describe(placement, prompt.trim());
    } finally {
      setIsSubmitting(false);
    }
  };
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center">
      {failed ? (
        <Text size="sm">This widget failed to build. Describe it again:</Text>
      ) : null}
      <form
        className="flex w-full items-center gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <Input
          autoFocus
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="What should go here?"
          disabled={isSubmitting}
        />
        <Button
          type="submit"
          size="sm"
          loading={isSubmitting}
          disabled={!prompt.trim() || isSubmitting}
        >
          {failed ? "Retry" : "Create"}
        </Button>
      </form>
      <div className="flex items-center gap-1">
        <DropdownMenu open={storeOpen} onOpenChange={setStoreOpen}>
          <DropdownMenuTrigger
            render={
              <Button variant="outline" size="sm">
                Choose from store…
              </Button>
            }
          />
          <DropdownMenuContent align="start">
            <div className="p-1">
              <Input
                value={storeSearch}
                onChange={(event) => setStoreSearch(event.target.value)}
                placeholder="Search components"
              />
            </div>
            {placeable.length === 0 ? (
              <DropdownMenuItem disabled>
                No published components yet. Describe the widget instead to
                build the first one.
              </DropdownMenuItem>
            ) : (
              placeable.map((component) => (
                <DropdownMenuItem
                  key={component.id}
                  onClick={() => actions.place(placement, component)}
                >
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate">{component.name}</span>
                    {component.description ? (
                      <span className="truncate text-xs opacity-70">
                        {component.description}
                      </span>
                    ) : null}
                  </div>
                </DropdownMenuItem>
              ))
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          variant="default"
          size="sm"
          onClick={() => actions.remove(placement)}
        >
          Remove
        </Button>
      </div>
    </div>
  );
}
