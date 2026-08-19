import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import { Button, Input, Spinner, Text } from "@posthog/quill";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ComponentFrame } from "./ComponentFrame";

// Poll cadence for the fill task's run status while a tile is generating —
// matches the canvas generation poll elsewhere.
const FILL_TASK_POLL_MS = 5_000;

export interface PlacementTileActions {
  /** Dispatch an agent task to fill this placement with the given ask. */
  describe: (placement: GridPlacement, prompt: string) => Promise<void>;
  /** Put a stalled placement back to pending so it can be re-described. */
  reset: (placement: GridPlacement) => void;
  /** Remove this placement from the layout. */
  remove: (placement: GridPlacement) => void;
  /** Open this placement's task conversation in the canvas's side panel. */
  discuss: (placement: GridPlacement) => void;
}

/**
 * One placement on the grid, rendered by lifecycle status: a live widget, a
 * drawn box awaiting its description, an agent filling it, or a failed fill
 * offering a retry.
 */
export function GridPlacementTile({
  placement,
  interactive,
  patching,
  actions,
}: {
  placement: GridPlacement;
  interactive: boolean;
  /** A layout write is in flight; the tile's edit buttons stay disabled until
   * it lands, so a second click can't fire a patch against the same head. */
  patching: boolean;
  actions: PlacementTileActions;
}) {
  if (placement.status === "live" && placement.component) {
    return <ComponentFrame placement={placement} />;
  }
  if (placement.status === "generating") {
    return (
      <GeneratingTile
        placement={placement}
        interactive={interactive}
        patching={patching}
        actions={actions}
      />
    );
  }
  return (
    <DescribeTile
      placement={placement}
      failed={placement.status === "failed"}
      interactive={interactive}
      patching={patching}
      actions={actions}
    />
  );
}

function GeneratingTile({
  placement,
  interactive,
  patching,
  actions,
}: {
  placement: GridPlacement;
  interactive: boolean;
  patching: boolean;
  actions: PlacementTileActions;
}) {
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
      onClick={() => actions.discuss(placement)}
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
              disabled={patching}
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
              onClick={() => actions.discuss(placement)}
            >
              Review request
            </Button>
          ) : null}
          {interactive ? (
            <Button
              variant="default"
              size="sm"
              disabled={patching}
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
            disabled={patching}
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
  patching,
  actions,
}: {
  placement: GridPlacement;
  failed: boolean;
  interactive: boolean;
  patching: boolean;
  actions: PlacementTileActions;
}) {
  const [prompt, setPrompt] = useState(placement.prompt ?? "");
  const [isSubmitting, setIsSubmitting] = useState(false);

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
      <Button
        variant="default"
        size="sm"
        disabled={patching}
        onClick={() => actions.remove(placement)}
      >
        Remove
      </Button>
    </div>
  );
}
