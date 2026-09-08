import {
  ChatCircleIcon,
  SidebarSimpleIcon,
  SpinnerGapIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Tabs,
  TabsList,
  TabsTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { TaskCommentsList } from "@posthog/ui/features/canvas/components/TaskCommentsList";
import { FreeformGenerateBar } from "@posthog/ui/features/canvas/freeform/FreeformGenerateBar";
import { useThreadConversation } from "@posthog/ui/features/canvas/hooks/useThreadConversation";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { Spin } from "@posthog/ui/primitives/Spinner";
import { useQuery } from "@tanstack/react-query";
import { type Ref, useEffect, useRef } from "react";

// The canvas's right-hand dock. It shows the chat of this person's run on the
// canvas (steering/queue included) when they have one; otherwise it shows the
// edit composer, which starts their first run. Header carries a minimize
// control that collapses the panel to a thin rail (handled by the parent).
export function CanvasSidePanel({
  chatTaskId,
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
  /** The run whose chat the panel shows: the current person's own run on this
   * canvas, or null when they have none. Another person's run never shows
   * here, even while it is in flight. */
  chatTaskId: string | null;
  commentTaskId: string | null;
  /** Whether the canvas is being edited. The composer is an edit affordance, so
   * view mode shows an empty chat when this person has no run. */
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
  const previousTaskId = useRef(chatTaskId);

  useEffect(() => {
    if (chatTaskId && chatTaskId !== previousTaskId.current) {
      setTab("chat");
    }
    previousTaskId.current = chatTaskId;
  }, [chatTaskId, setTab]);

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
        ) : !interactive ? (
          <Empty className="h-full border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ChatCircleIcon size={24} />
              </EmptyMedia>
              <EmptyTitle>No run yet</EmptyTitle>
              <EmptyDescription>
                Select Edit to start an agent run on this canvas. Its chat shows
                here.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="p-3">
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
        <Spin className="text-gray-9">
          <SpinnerGapIcon size={18} />
        </Spin>
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
        <Spin className="text-gray-9">
          <SpinnerGapIcon size={18} />
        </Spin>
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
