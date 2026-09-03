import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import { Button, Spinner, Text } from "@posthog/quill";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ComponentFrame } from "./ComponentFrame";
import type { PlacementActions } from "./placementActions";

// Poll cadence for the fill task's run status while a tile is generating —
// matches the canvas generation poll elsewhere.
const FILL_TASK_POLL_MS = 5_000;

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
  actions: PlacementActions;
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
  actions: PlacementActions;
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
      {viewTask}
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
  actions: PlacementActions;
}) {
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
  const submit = async (text: string) => {
    const instruction = text.trim();
    if (!instruction || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await actions.describe(placement, instruction);
    } finally {
      setIsSubmitting(false);
    }
  };
  return (
    <div className="flex h-full w-full flex-col justify-center gap-2 p-3">
      {failed ? (
        <Text size="sm">This widget failed to build. Describe it again:</Text>
      ) : null}
      {/* The task composer's editor, as the freeform canvas uses it: markdown
          as you type, shift+enter for a new line, @ for files and / for
          skills. Its own toolbar stays hidden; card actions live in the shared
          overflow menu above this tile. */}
      <PromptInput
        sessionId={`grid-placement-${placement.id}`}
        placeholder="What should go here?"
        // A failed fill keeps what was asked for, so the retry starts from it
        // unless a draft is already waiting in the box.
        initialContent={placement.prompt ?? undefined}
        autoFocus
        disabled={isSubmitting}
        isLoading={isSubmitting}
        enableCommands
        enableBashMode={false}
        hideDefaultToolbar
        onSubmit={(text) => void submit(text)}
      />
    </div>
  );
}
