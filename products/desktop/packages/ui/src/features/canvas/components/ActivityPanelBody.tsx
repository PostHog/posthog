import { ArrowDownIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { ActivityTimeline } from "@posthog/ui/features/canvas/components/ActivityTimeline";
import { ActivityLoadingState } from "@posthog/ui/features/canvas/components/activityRows";
import { TaskArtifactsList } from "@posthog/ui/features/canvas/components/TaskArtifactsList";
import { TaskCommentsList } from "@posthog/ui/features/canvas/components/TaskCommentsList";
import { AgentStatusLine } from "@posthog/ui/features/canvas/components/ThreadPanel";
import { useThreadConversation } from "@posthog/ui/features/canvas/hooks/useThreadConversation";
import { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { mergeConversationItems } from "@posthog/ui/features/sessions/components/mergeConversationItems";
import {
  useOptimisticItemsForTask,
  useSessionIsCloud,
} from "@posthog/ui/features/sessions/sessionStore";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type ActivityTab = "timeline" | "artifacts" | "comments";

// Within this much of the bottom still counts as watching the end, so a row arriving
// mid-poll keeps following. Wide enough to survive a partially scrolled last row.
const AT_BOTTOM_SLACK_PX = 48;

/**
 * A session's activity: its timeline, artifacts, or comments. Which one is
 * picked by the panel above it, either the tabbed dock (ActivityPanel) or the
 * chrome's right panel (RightPanel), so the three lists behave the same
 * wherever they are drawn.
 */
export function ActivityPanelBody({
  task,
  tab,
  canOpenInPlace,
}: {
  task: Task;
  tab: ActivityTab;
  /** Set where the task's own view (transcript, review pane) is mounted beside
   *  this body, so activity rows can drive it instead of going nowhere. */
  canOpenInPlace?: boolean;
}) {
  const taskId = task.id;
  const {
    timeline,
    messages,
    agentStatus,
    events,
    isPromptPending,
    hasLoadedThread,
    currentUser,
  } = useThreadConversation(task, { surface: "activity_panel" });

  // Draw once the thread has answered, and never take the timeline away again.
  // Gating on the live session (`isReady`) blinks a loader over drawn rows while it
  // connects. The latch is set on commit, because Strict Mode and concurrent
  // rendering abandon renders that would otherwise set it.
  const hasDrawnTimeline = useRef(false);
  const timelineReady = hasDrawnTimeline.current || hasLoadedThread;
  useEffect(() => {
    if (hasLoadedThread) hasDrawnTimeline.current = true;
  }, [hasLoadedThread]);

  // Merged exactly as the transcript merges it, because "Show in chat" hands the transcript
  // one of these item ids. A prompt still waiting on its echo is an optimistic item there and
  // the server copy is dropped, so raw events alone would name a row it does not render.
  const optimisticItems = useOptimisticItemsForTask(taskId);
  const isCloudSession = useSessionIsCloud(taskId);
  const conversationItems = useMemo(
    () =>
      tab === "timeline"
        ? mergeConversationItems({
            conversationItems: buildConversationItems(events, isPromptPending)
              .items,
            optimisticItems,
            isCloud: isCloudSession,
          })
        : [],
    [tab, events, isPromptPending, optimisticItems, isCloudSession],
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const [hasNewerBelow, setHasNewerBelow] = useState(false);
  const scrollToLatest = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight });
    setHasNewerBelow(false);
  }, []);
  const onScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const atBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight <=
      AT_BOTTOM_SLACK_PX;
    if (atBottom) setHasNewerBelow(false);
  }, []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: follow the end when rendered content changes
  useEffect(() => {
    // Only the timeline reads bottom-up; the other tabs put what matters on top.
    if (tab !== "timeline") return;
    const node = scrollRef.current;
    if (!node) return;
    // Following unconditionally yanks the panel to the bottom on every refetch while someone
    // is reading further up, so follow only for a reader already at the end.
    const atBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight <=
      AT_BOTTOM_SLACK_PX;
    if (atBottom) {
      node.scrollTo({ top: node.scrollHeight });
      setHasNewerBelow(false);
      return;
    }
    setHasNewerBelow(true);
  }, [timeline, events.length, agentStatus?.phase, tab]);

  const body = () => {
    if (tab === "comments") {
      return <TaskCommentsList task={task} timeline={timeline} />;
    }
    if (tab === "artifacts") {
      return (
        <TaskArtifactsList
          task={task}
          timeline={timeline}
          canOpenInPlace={canOpenInPlace}
        />
      );
    }
    if (!timelineReady) return <ActivityLoadingState />;
    return (
      <ActivityTimeline
        task={task}
        timeline={timeline}
        messages={messages}
        conversationItems={conversationItems}
        currentUserId={currentUser?.id}
        canOpenInPlace={canOpenInPlace}
      />
    );
  };

  return (
    <>
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          aria-busy={!timelineReady}
          className="flex-1 overflow-y-auto"
        >
          {body()}
        </div>
        {tab === "timeline" && hasNewerBelow && (
          <Button
            variant="default"
            size="sm"
            className="-translate-x-1/2 absolute bottom-2 left-1/2 z-20 shadow-md"
            onClick={scrollToLatest}
          >
            <ArrowDownIcon size={12} />
            New activity
          </Button>
        )}
      </div>

      {tab === "timeline" && agentStatus && (
        <AgentStatusLine status={agentStatus} />
      )}
    </>
  );
}
