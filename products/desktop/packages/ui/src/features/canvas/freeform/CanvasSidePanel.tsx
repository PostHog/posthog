import { SidebarSimpleIcon, SpinnerGapIcon } from "@phosphor-icons/react";
import {
  Button,
  Tabs,
  TabsList,
  TabsTrigger,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { TaskCommentsList } from "@posthog/ui/features/canvas/components/TaskCommentsList";
import { CanvasContextEditor } from "@posthog/ui/features/canvas/freeform/ContextEditor";
import { FreeformGenerateBar } from "@posthog/ui/features/canvas/freeform/FreeformGenerateBar";
import { useThreadConversation } from "@posthog/ui/features/canvas/hooks/useThreadConversation";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { type Ref, useEffect, useRef } from "react";

// The canvas's right-hand dock. While a generation/edit run is in flight it
// shows that run's live chat (steering/queue included); otherwise it shows the
// edit composer for the next change. Header carries a minimize control that
// collapses the panel to a thin rail (handled by the parent).
export function CanvasSidePanel({
  effectiveTaskId,
  commentTaskId,
  interactive,
  onMinimize,
  dashboardId,
  channelId,
  channelName,
  name,
  displayedVersionId,
  commentVersionLabel,
  onCommentOpen,
  templateId,
  isEdit,
  editorRef,
  onStarted,
}: {
  effectiveTaskId: string | null;
  commentTaskId: string | null;
  /** Whether the canvas is being edited. The composer is an edit affordance, so
   * view mode falls back to the conversation that last built the canvas. */
  interactive?: boolean;
  onMinimize: () => void;
  dashboardId: string;
  channelId: string;
  channelName: string;
  name: string;
  displayedVersionId: string | null;
  commentVersionLabel: (versionId: string) => string | null;
  onCommentOpen: (versionId: string | null) => void;
  templateId?: string;
  /** Whether the canvas already has published source (a follow-up edit rather
   * than a first build) — the agent re-reads the live source itself. */
  isEdit?: boolean;
  // Exposes the edit composer's editor so self-repair can prefill it.
  editorRef?: Ref<EditorHandle>;
  onStarted?: (taskId: string) => void;
}) {
  const tab = useCanvasChatPanelStore((state) => state.tab);
  const setTab = useCanvasChatPanelStore((state) => state.setTab);
  const previousTaskId = useRef(effectiveTaskId);
  // With no run in flight, edit mode gets the composer for the next change,
  // while view mode gets the chat of the run that produced this canvas.
  const chatTaskId = effectiveTaskId ?? (interactive ? null : commentTaskId);

  useEffect(() => {
    if (effectiveTaskId && effectiveTaskId !== previousTaskId.current) {
      setTab("chat");
    }
    previousTaskId.current = effectiveTaskId;
  }, [effectiveTaskId, setTab]);

  return (
    <div className="flex h-full min-w-0 flex-col bg-gray-1">
      <div className="flex h-10 shrink-0 items-center justify-between border-b bg-chrome pr-2 pl-3">
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
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                size="icon"
                variant="default"
                aria-label="Minimize panel"
                onClick={onMinimize}
              >
                <SidebarSimpleIcon size={16} />
              </Button>
            }
          />
          <TooltipContent>Minimize panel</TooltipContent>
        </Tooltip>
      </div>

      <div className="min-h-0 flex-1">
        {tab === "comments" && commentTaskId ? (
          <CanvasCommentsLoader
            taskId={commentTaskId}
            dashboardId={dashboardId}
            name={name}
            displayedVersionId={displayedVersionId}
            commentVersionLabel={commentVersionLabel}
            onCommentOpen={onCommentOpen}
          />
        ) : chatTaskId ? (
          <CanvasChatLoader taskId={chatTaskId} />
        ) : (
          <div className="flex h-full min-h-0 flex-col gap-3 p-3">
            <FreeformGenerateBar
              ref={editorRef}
              sessionId={`canvas:${dashboardId}`}
              dashboardId={dashboardId}
              channelId={channelId}
              channelName={channelName}
              name={name}
              templateId={templateId}
              isEdit={isEdit}
              onStarted={onStarted}
            />
            {/* The author context (markdown): background the agent reads on
                every generation. Edits against the saved record, autosaving
                on blur. */}
            <div className="flex min-h-0 flex-1 flex-col gap-1">
              <Text size="xs" variant="muted" className="shrink-0">
                Context: notes the agent reads on every generation
              </Text>
              <div className="min-h-0 flex-1 overflow-hidden rounded-md border">
                <CanvasContextEditor dashboardId={dashboardId} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Resolves the run's task (shared react-query cache, so this dedupes with the
// canvas view's own poll) and renders its live chat once available.
function CanvasChatLoader({ taskId }: { taskId: string }) {
  const { data: task } = useQuery(taskDetailQuery(taskId));

  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <SpinnerGapIcon size={18} className="animate-spin text-gray-9" />
      </div>
    );
  }

  return <EmbeddedSessionView task={task} />;
}

function CanvasCommentsLoader({
  taskId,
  dashboardId,
  name,
  displayedVersionId,
  commentVersionLabel,
  onCommentOpen,
}: {
  taskId: string;
  dashboardId: string;
  name: string;
  displayedVersionId: string | null;
  commentVersionLabel: (versionId: string) => string | null;
  onCommentOpen: (versionId: string | null) => void;
}) {
  const { data: task } = useQuery(taskDetailQuery(taskId));

  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <SpinnerGapIcon size={18} className="animate-spin text-gray-9" />
      </div>
    );
  }

  return (
    <CanvasTaskComments
      task={task}
      dashboardId={dashboardId}
      name={name}
      displayedVersionId={displayedVersionId}
      commentVersionLabel={commentVersionLabel}
      onCommentOpen={onCommentOpen}
    />
  );
}

function CanvasTaskComments({
  task,
  dashboardId,
  name,
  displayedVersionId,
  commentVersionLabel,
  onCommentOpen,
}: {
  task: Task;
  dashboardId: string;
  name: string;
  displayedVersionId: string | null;
  commentVersionLabel: (versionId: string) => string | null;
  onCommentOpen: (versionId: string | null) => void;
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
        name,
        target: { scope: "desktop_canvas", itemId: dashboardId },
        url: null,
      }}
      canvasVersionId={displayedVersionId}
      commentVersionLabel={commentVersionLabel}
      onCanvasCommentOpen={onCommentOpen}
    />
  );
}
