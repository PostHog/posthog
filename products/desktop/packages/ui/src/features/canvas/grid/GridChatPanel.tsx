import { XIcon } from "@phosphor-icons/react";
import { Button, Input, Spinner, Text } from "@posthog/quill";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

/** What the panel talks about: a widget's fill task, or the whole canvas. */
export interface GridChatTarget {
  /** Existing conversation to open; null offers a composer to start one. */
  taskId: string | null;
  title: string;
}

/**
 * Right-hand conversation panel for a grid canvas: opens a widget's fill task
 * (steer it, approve its permission requests, ask for fixes) or a canvas-wide
 * task that can edit the whole layout. Kept separate from the freeform
 * CanvasSidePanel, whose versions/comments/self-repair don't apply to grids.
 */
export function GridChatPanel({
  target,
  canvasId,
  canvasName,
  channelId,
  onClose,
  onStarted,
}: {
  target: GridChatTarget;
  canvasId: string;
  canvasName: string;
  channelId: string;
  onClose: () => void;
  /** A canvas-wide task was started from the panel's composer. */
  onStarted: (taskId: string) => void;
}) {
  return (
    <div className="flex h-full w-[380px] shrink-0 flex-col border-(--gray-5) border-l">
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-(--gray-5) border-b px-3">
        <Text size="sm" weight="medium" className="truncate">
          {target.title}
        </Text>
        <Button variant="default" size="icon" onClick={onClose}>
          <XIcon size={14} />
        </Button>
      </div>
      {target.taskId ? (
        <TaskChat taskId={target.taskId} />
      ) : (
        <CanvasChatComposer
          canvasId={canvasId}
          canvasName={canvasName}
          channelId={channelId}
          onStarted={onStarted}
        />
      )}
    </div>
  );
}

// Resolves the task (shared react-query cache) and renders its live chat —
// follow-ups, steering, and permission approvals all happen in here.
function TaskChat({ taskId }: { taskId: string }) {
  const { data: task } = useQuery(taskDetailQuery(taskId));
  if (!task) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return <EmbeddedSessionView task={task} />;
}

// No canvas-wide conversation yet: a one-field composer that starts one.
function CanvasChatComposer({
  canvasId,
  canvasName,
  channelId,
  onStarted,
}: {
  canvasId: string;
  canvasName: string;
  channelId: string;
  onStarted: (taskId: string) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const { generate } = useGenerateFreeformCanvas({
    channelId,
    channelName: "",
  });

  const submit = async () => {
    if (!instruction.trim() || isStarting) return;
    setIsStarting(true);
    try {
      const taskId = await generate({
        dashboardId: canvasId,
        name: canvasName,
        instruction: instruction.trim(),
        canvasKind: "grid",
      });
      if (taskId) onStarted(taskId);
    } finally {
      setIsStarting(false);
    }
  };

  return (
    <div className="flex flex-1 flex-col justify-center gap-2 p-4">
      <Text size="sm">
        Ask the agent to change anything on this canvas: add or fix widgets,
        rearrange the grid, or clean it up.
      </Text>
      <form
        className="flex items-center gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <Input
          autoFocus
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="What should change?"
          disabled={isStarting}
        />
        <Button
          type="submit"
          size="sm"
          loading={isStarting}
          disabled={!instruction.trim() || isStarting}
        >
          Start
        </Button>
      </form>
    </div>
  );
}
