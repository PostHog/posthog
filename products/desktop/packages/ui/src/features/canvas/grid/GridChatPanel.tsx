import { CaretLeftIcon, SidebarSimpleIcon } from "@phosphor-icons/react";
import { Button, Input, Spinner, Text } from "@posthog/quill";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

/** A widget conversation the panel is temporarily focused on. */
export interface GridChatTarget {
  taskId: string | null;
  title: string;
}

/**
 * The grid canvas's right-hand dock, mirroring the freeform canvas panel:
 * edit mode opens it on the canvas's own conversation (with the version the
 * grid is on), and a widget's chat affordances refocus it on that widget's
 * fill task — follow-ups, steering, and permission approvals all in place.
 */
export function GridChatPanel({
  target,
  canvasTaskId,
  versionLabel,
  canvasId,
  canvasName,
  channelId,
  onBack,
  onMinimize,
  onStarted,
}: {
  /** Widget focus, or null for the canvas's own conversation. */
  target: GridChatTarget | null;
  /** The recorded canvas-wide conversation, if one has been started. */
  canvasTaskId: string | null;
  /** Label of the layout version currently shown (e.g. "V4"). */
  versionLabel: string | null;
  canvasId: string;
  canvasName: string;
  channelId: string;
  /** Return from a widget's conversation to the canvas's. */
  onBack: () => void;
  onMinimize: () => void;
  /** A canvas-wide task was started from the panel's composer. */
  onStarted: (taskId: string) => void;
}) {
  const taskId = target ? target.taskId : canvasTaskId;
  return (
    <div className="flex h-full flex-col border-(--gray-5) border-l">
      <div className="flex h-10 shrink-0 items-center gap-1 border-(--gray-5) border-b px-2">
        {target ? (
          <Button
            variant="default"
            size="icon"
            aria-label="Back to canvas chat"
            onClick={onBack}
          >
            <CaretLeftIcon size={14} />
          </Button>
        ) : null}
        <Text size="sm" weight="medium" className="min-w-0 flex-1 truncate">
          {target ? target.title : "Canvas chat"}
        </Text>
        {versionLabel ? (
          <Text size="sm" className="shrink-0 opacity-70">
            {versionLabel}
          </Text>
        ) : null}
        <Button
          variant="default"
          size="icon"
          aria-label="Hide panel"
          onClick={onMinimize}
        >
          <SidebarSimpleIcon size={14} />
        </Button>
      </div>
      {taskId ? (
        <TaskChat taskId={taskId} />
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
