import {
  ChatCircleIcon,
  ChatTeardropTextIcon,
  type Icon,
  PulseIcon,
  SidebarSimpleIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { CanvasBlocksPanel } from "@posthog/ui/features/canvas/blocks/CanvasBlocksPanel";
import { TaskCommentsList } from "@posthog/ui/features/canvas/components/TaskCommentsList";
import { CanvasTimeline } from "@posthog/ui/features/canvas/freeform/CanvasTimeline";
import { FreeformGenerateBar } from "@posthog/ui/features/canvas/freeform/FreeformGenerateBar";
import {
  type CanvasPanelTab,
  useCanvasChatPanelStore,
} from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { useQuery } from "@tanstack/react-query";
import { type Ref, useEffect, useRef } from "react";

const PANEL_TABS: Record<CanvasPanelTab, { label: string; Icon: Icon }> = {
  chat: { label: "Chat", Icon: ChatTeardropTextIcon },
  blocks: { label: "Blocks", Icon: SquaresFourIcon },
  comments: { label: "Comments", Icon: ChatCircleIcon },
  timeline: { label: "Timeline", Icon: PulseIcon },
};

const TAB_ORDER: readonly CanvasPanelTab[] = [
  "chat",
  "blocks",
  "comments",
  "timeline",
];

function PanelTabButton({
  tab,
  active,
  disabled,
  onSelect,
}: {
  tab: CanvasPanelTab;
  active: boolean;
  disabled: boolean;
  onSelect: (tab: CanvasPanelTab) => void;
}) {
  const { label, Icon } = PANEL_TABS[tab];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={label}
            aria-pressed={active}
            data-selected={active || undefined}
            disabled={disabled}
            onClick={() => onSelect(tab)}
            className="text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          >
            <Icon size={16} />
          </Button>
        }
      />
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

// The canvas's right-hand dock. It shows the chat of this person's run on the
// canvas (steering/queue included) when they have one; otherwise it shows the
// edit composer, which starts their first run. Header carries a minimize
// control that collapses the panel to a thin rail (handled by the parent).
export function CanvasSidePanel({
  chatTaskId,
  commentTaskId,
  commentsEnabled,
  interactive,
  onMinimize,
  dashboardId,
  channelId,
  channelName,
  name,
  displayedVersionId,
  liveVersionId,
  commentVersionLabel,
  onCommentOpen,
  templateId,
  isEdit,
  editorRef,
  onStarted,
  onAskAgent,
}: {
  /** The run whose chat the panel shows: the current person's own run on this
   * canvas, or null when they have none. Another person's run never shows
   * here, even while it is in flight. */
  chatTaskId: string | null;
  commentTaskId: string | null;
  commentsEnabled: boolean;
  /** Whether the canvas is being edited. The composer is an edit affordance, so
   * view mode shows an empty chat when this person has no run. */
  interactive?: boolean;
  onMinimize: () => void;
  dashboardId: string;
  channelId: string;
  channelName: string;
  name: string;
  displayedVersionId: string | null;
  liveVersionId: string | null;
  commentVersionLabel: (versionId: string) => string | null;
  onCommentOpen: (versionId: string | null) => void;
  templateId?: string;
  /** Whether the canvas already has published source (a follow-up edit rather
   * than a first build) — the agent re-reads the live source itself. */
  isEdit?: boolean;
  // Exposes the edit composer's editor so self-repair can prefill it.
  editorRef?: Ref<EditorHandle>;
  onStarted?: (taskId: string) => void;
  onAskAgent: (message: string) => void;
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

  const firstBuildRunning = !!chatTaskId && !isEdit;
  const visibleTab: CanvasPanelTab =
    tab === "blocks" && (!interactive || firstBuildRunning) ? "chat" : tab;

  return (
    <div className="flex h-full min-w-0 flex-col bg-gray-1">
      <ChromeBar
        className="bg-chrome"
        actions={
          <TooltipProvider delay={400}>
            <div className="flex items-center gap-0.5">
              {TAB_ORDER.filter(
                (option) => option !== "blocks" || interactive,
              ).map((option) => (
                <PanelTabButton
                  key={option}
                  tab={option}
                  active={visibleTab === option}
                  disabled={
                    (option === "comments" && !commentsEnabled) ||
                    (option === "blocks" && firstBuildRunning)
                  }
                  onSelect={setTab}
                />
              ))}
              <span aria-hidden className="mx-1 h-4 w-px bg-border" />
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      size="icon-sm"
                      variant="default"
                      aria-label="Minimize panel"
                      onClick={onMinimize}
                      className="text-muted-foreground"
                    >
                      <SidebarSimpleIcon size={16} />
                    </Button>
                  }
                />
                <TooltipContent side="bottom">Minimize panel</TooltipContent>
              </Tooltip>
            </div>
          </TooltipProvider>
        }
      >
        <span className="min-w-0 flex-1 truncate font-medium text-[13px]">
          {PANEL_TABS[visibleTab].label}
        </span>
      </ChromeBar>

      <div className="min-h-0 flex-1">
        {visibleTab === "blocks" ? (
          <CanvasBlocksPanel canvasId={dashboardId} onAskAgent={onAskAgent} />
        ) : visibleTab === "timeline" ? (
          <CanvasTimeline
            dashboardId={dashboardId}
            liveVersionId={liveVersionId}
            viewingVersionId={displayedVersionId}
            versionLabel={commentVersionLabel}
            onOpen={onCommentOpen}
          />
        ) : visibleTab === "comments" && commentsEnabled ? (
          <CanvasComments
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
    return <LoadingState />;
  }

  return <EmbeddedSessionView task={task} />;
}

function CanvasComments({
  taskId,
  dashboardId,
  name,
  displayedVersionId,
  commentVersionLabel,
  onCommentOpen,
}: {
  taskId: string | null;
  dashboardId: string;
  name: string;
  displayedVersionId: string | null;
  commentVersionLabel: (versionId: string) => string | null;
  onCommentOpen: (versionId: string | null) => void;
}) {
  return (
    <TaskCommentsList
      taskId={taskId}
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
