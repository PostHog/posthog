import { CaretLeftIcon, SidebarSimpleIcon } from "@phosphor-icons/react";
import {
  Button,
  Input,
  Spinner,
  Tabs,
  TabsList,
  TabsTrigger,
  Text,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { TaskCommentsList } from "@posthog/ui/features/canvas/components/TaskCommentsList";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { useThreadConversation } from "@posthog/ui/features/canvas/hooks/useThreadConversation";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
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
 * edit mode opens it on the canvas's own conversation (with a comments tab
 * beside it), and a widget's chat affordances refocus it on that widget's
 * fill task — follow-ups, steering, and permission approvals all in place.
 * The version the grid is on shows in the canvas toolbar, like freeform.
 */
export function GridChatPanel({
  target,
  canvasTaskId,
  commentTaskId,
  canvasVersionId,
  commentVersionLabel,
  canvasId,
  canvasName,
  channelId,
  channelName,
  onBack,
  onMinimize,
  onStarted,
}: {
  /** Widget focus, or null for the canvas's own conversation. */
  target: GridChatTarget | null;
  /** The recorded canvas-wide conversation, if one has been started. */
  canvasTaskId: string | null;
  /** The task canvas comments anchor to (the canvas conversation, or the run
   * that produced the current layout). Null disables the comments tab. */
  commentTaskId: string | null;
  /** The layout version currently shown, for labeling new comments. */
  canvasVersionId: string | null;
  commentVersionLabel: (versionId: string) => string | null;
  canvasId: string;
  canvasName: string;
  channelId: string;
  /** The channel's display name, so a started run names its channel. */
  channelName: string;
  /** Return from a widget's conversation to the canvas's. */
  onBack: () => void;
  onMinimize: () => void;
  /** A canvas-wide task was started from the panel's composer. */
  onStarted: (taskId: string) => void;
}) {
  const tab = useCanvasChatPanelStore((state) => state.tab);
  const setTab = useCanvasChatPanelStore((state) => state.setTab);
  const minimize = (
    <Button
      variant="default"
      size="icon"
      aria-label="Hide panel"
      onClick={onMinimize}
    >
      <SidebarSimpleIcon size={14} />
    </Button>
  );

  if (target) {
    return (
      <div className="flex h-full flex-col border-(--gray-5) border-l">
        <div className="flex h-10 shrink-0 items-center gap-1 border-(--gray-5) border-b px-2">
          <Button
            variant="default"
            size="icon"
            aria-label="Back to canvas chat"
            onClick={onBack}
          >
            <CaretLeftIcon size={14} />
          </Button>
          <Text size="sm" weight="medium" className="min-w-0 flex-1 truncate">
            {target.title}
          </Text>
          {minimize}
        </div>
        {target.taskId ? (
          <TaskChat taskId={target.taskId} />
        ) : (
          <div className="flex flex-1 items-center justify-center p-4">
            <Text size="sm">This widget has no conversation yet.</Text>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col border-(--gray-5) border-l">
      <div className="flex h-10 shrink-0 items-center justify-between border-(--gray-5) border-b pr-2 pl-3">
        <Tabs
          value={tab}
          onValueChange={(value) => setTab(value as "chat" | "comments")}
        >
          <TabsList variant="line" className="h-10 gap-1 p-0">
            <TabsTrigger value="chat" className="px-2.5">
              Chat
            </TabsTrigger>
            <TabsTrigger
              value="comments"
              disabled={!commentTaskId}
              className="px-2.5"
            >
              Comments
            </TabsTrigger>
          </TabsList>
        </Tabs>
        {minimize}
      </div>
      {tab === "comments" && commentTaskId ? (
        <CanvasComments
          taskId={commentTaskId}
          canvasId={canvasId}
          canvasName={canvasName}
          canvasVersionId={canvasVersionId}
          commentVersionLabel={commentVersionLabel}
        />
      ) : canvasTaskId ? (
        <TaskChat taskId={canvasTaskId} />
      ) : (
        <CanvasChatComposer
          canvasId={canvasId}
          canvasName={canvasName}
          channelId={channelId}
          channelName={channelName}
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
  // Constrain the chat body like the comments branch beside it: a shrinkable
  // flex child below the fixed header needs min-h-0 so it fills the remaining
  // height instead of growing past the panel.
  return (
    <div className="min-h-0 flex-1">
      <EmbeddedSessionView task={task} />
    </div>
  );
}

// The canvas's comment threads, anchored to its conversation task: read,
// reply, resolve, and add new ones. The agent reads the same threads.
function CanvasComments({
  taskId,
  canvasId,
  canvasName,
  canvasVersionId,
  commentVersionLabel,
}: {
  taskId: string;
  canvasId: string;
  canvasName: string;
  canvasVersionId: string | null;
  commentVersionLabel: (versionId: string) => string | null;
}) {
  const { data: task } = useQuery(taskDetailQuery(taskId));
  if (!task) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1">
      <GridCanvasComments
        task={task}
        canvasId={canvasId}
        canvasName={canvasName}
        canvasVersionId={canvasVersionId}
        commentVersionLabel={commentVersionLabel}
      />
    </div>
  );
}

// Its own component so useThreadConversation runs only once the task exists.
function GridCanvasComments({
  task,
  canvasId,
  canvasName,
  canvasVersionId,
  commentVersionLabel,
}: {
  task: Task;
  canvasId: string;
  canvasName: string;
  canvasVersionId: string | null;
  commentVersionLabel: (versionId: string) => string | null;
}) {
  const { timeline } = useThreadConversation(task, {
    surface: "activity_panel",
  });
  return (
    <TaskCommentsList
      task={task}
      timeline={timeline}
      onlySource={{
        kind: "canvas",
        name: canvasName,
        target: { scope: "desktop_canvas", itemId: canvasId },
        url: null,
      }}
      canvasVersionId={canvasVersionId}
      commentVersionLabel={commentVersionLabel}
    />
  );
}

// No canvas-wide conversation yet: a one-field composer that starts one.
function CanvasChatComposer({
  canvasId,
  canvasName,
  channelId,
  channelName,
  onStarted,
}: {
  canvasId: string;
  canvasName: string;
  channelId: string;
  channelName: string;
  onStarted: (taskId: string) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const { generate } = useGenerateFreeformCanvas({
    channelId,
    channelName,
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
