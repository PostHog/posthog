import { FileTextIcon, ScrollIcon } from "@phosphor-icons/react";
import type {
  ArtifactPayload,
  CommentEventPayload,
} from "@posthog/core/canvas/activityEvents";
import {
  type GroupedActivityRow,
  groupActivityRows,
} from "@posthog/core/canvas/activityGrouping";
import {
  buildActivityTimeline,
  type UserMessageLike,
} from "@posthog/core/canvas/activityTimeline";
import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
import { DEFAULT_TAB_IDS } from "@posthog/core/panels/panelConstants";
import { findTabInTree } from "@posthog/core/panels/panelTree";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  ThreadItemGroup,
} from "@posthog/quill";
import type {
  Task,
  TaskCommentThreadSummary,
  TaskThreadMessage,
  UserBasic,
} from "@posthog/shared/domain-types";
import {
  ActivityEventRow,
  ArtifactEventDetail,
  CommentEventRow,
  CommentRow,
  CommentStateRow,
  CREATED_BADGE,
  GroupedEventRow,
  MESSAGE_BADGE,
  MessageBubble,
  PersonBead,
  RunStatusRow,
  ThreadReplyRow,
  TimelineRow,
} from "@posthog/ui/features/canvas/components/activityRows";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { ThreadArtifactCard } from "@posthog/ui/features/canvas/components/ThreadPanel";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import type { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { extractCanvasInstructions } from "@posthog/ui/features/sessions/components/session-update/canvasInstructions";
import { extractChannelContext } from "@posthog/ui/features/sessions/components/session-update/channelContext";
import { extractCustomInstructions } from "@posthog/ui/features/sessions/components/session-update/customInstructions";
import { collapsePiSkillInvocation } from "@posthog/ui/features/sessions/components/session-update/piSkillInvocation";
import {
  useHasTranscriptListener,
  useThreadNavigationStore,
} from "@posthog/ui/features/sessions/threadNavigationStore";
import { Fragment, useMemo } from "react";

type ConversationItem = ReturnType<
  typeof buildConversationItems
>["items"][number];

function UserMessageRow({
  author,
  content,
  timestamp,
  connectedAbove,
  connectedBelow,
  onShowInChat,
}: {
  author?: UserBasic | null;
  content: string;
  timestamp: string;
  connectedAbove: boolean;
  connectedBelow: boolean;
  onShowInChat?: () => void;
}) {
  const name = author ? userDisplayName(author) : "You";
  const channelContext = useMemo(
    () => extractChannelContext(content),
    [content],
  );
  const afterChannelContext = channelContext?.stripped ?? content;
  // Every block the chat strips has to be stripped here too, or the raw XML shows up on
  // the timeline for a viewer whose chat hid it.
  const canvasInstructions = useMemo(
    () => extractCanvasInstructions(afterChannelContext),
    [afterChannelContext],
  );
  const afterCanvasInstructions =
    canvasInstructions?.stripped ?? afterChannelContext;
  const customInstructions = useMemo(
    () => extractCustomInstructions(afterCanvasInstructions),
    [afterCanvasInstructions],
  );
  const displayContent = collapsePiSkillInvocation(
    customInstructions?.stripped ?? afterCanvasInstructions,
  );
  const trimmed = displayContent.trim();
  const firstLine = trimmed.split("\n", 1)[0] ?? "";
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={<PersonBead user={author} badge={MESSAGE_BADGE} />}
      timestamp={timestamp}
      onShowInChat={onShowInChat}
      detail={
        <div className="space-y-1.5">
          <MessageBubble content={displayContent} />
          {canvasInstructions && (
            <Collapsible className="min-w-0 bg-transparent hover:bg-transparent data-open:bg-transparent">
              <CollapsibleTrigger className="min-h-0 w-full bg-transparent px-0 py-1 text-left hover:bg-transparent aria-expanded:bg-transparent">
                <ScrollIcon size={12} />
                <span className="truncate text-xs">Canvas instructions</span>
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted p-2 text-muted-foreground text-xs">
                {canvasInstructions.body}
              </CollapsibleContent>
            </Collapsible>
          )}
          {channelContext && (
            <Collapsible className="min-w-0 bg-transparent hover:bg-transparent data-open:bg-transparent">
              <CollapsibleTrigger className="min-h-0 w-full bg-transparent px-0 py-1 text-left hover:bg-transparent aria-expanded:bg-transparent">
                <FileTextIcon size={12} />
                <span className="truncate text-xs">
                  {channelContext.mention.name
                    ? `${channelDisplayLabel(channelContext.mention.name)} `
                    : ""}
                  CONTEXT.md
                </span>
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted p-2 text-muted-foreground text-xs">
                {channelContext.mention.body}
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      }
    >
      <span className="font-medium">{name}</span>{" "}
      {/* Through MentionText like the body: a preview that prints raw mention or chip
          markup is the same bug as a body that does. */}
      <span className="text-muted-foreground">
        <MentionText content={firstLine} />
      </span>
    </TimelineRow>
  );
}

/** An inline `= []` default is a new array on every render, which would rebuild the timeline
 *  through the memo's dependency list. */
const NO_COMMENT_THREADS: TaskCommentThreadSummary[] = [];

export function ActivityTimeline({
  task,
  timeline,
  messages,
  conversationItems,
  commentThreads = NO_COMMENT_THREADS,
  currentUserId,
  canOpenInPlace,
}: {
  task: Task;
  timeline: ThreadTimelineRow<TaskThreadMessage>[];
  /** The event rows live among the agent-authored messages, which `timeline` filters out,
   *  so they have to arrive separately. */
  messages: TaskThreadMessage[];
  conversationItems: ConversationItem[];
  commentThreads?: TaskCommentThreadSummary[];
  currentUserId?: number;
  /** True when the task's transcript and review pane are mounted beside this pane. False in
   *  the channel-home sidebar, where rows stay inert and PRs open externally instead. */
  canOpenInPlace?: boolean;
}) {
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );

  const messageRows = useMemo(() => {
    const byId = new Map<string, ThreadTimelineRow<TaskThreadMessage>>();
    for (const row of timeline) byId.set(row.message.id, row);
    return byId;
  }, [timeline]);

  const timelineRows = useMemo(() => {
    const taskCreatedTimestamp = Date.parse(task.created_at);
    return buildActivityTimeline({
      task: {
        id: task.id,
        createdAt: task.created_at,
        updatedAt: task.updated_at,
        latestRunId: task.latest_run?.id ?? null,
        latestRunStatus: task.latest_run?.status ?? null,
        latestRunPrUrl:
          typeof task.latest_run?.output?.pr_url === "string"
            ? task.latest_run.output.pr_url
            : null,
      },
      messages,
      commentThreads: commentThreads.map((thread) => ({
        id: thread.id,
        lastActivityAt: thread.last_activity_at,
        mentionedUserIds: thread.mentioned_user_ids ?? [],
        resolved: thread.resolved,
        stateEvent: thread.state_event
          ? {
              state: thread.state_event.state,
              createdAt: thread.state_event.created_at,
            }
          : null,
      })),
      userMessages: conversationItems.reduce<UserMessageLike[]>(
        (items, item) => {
          if (item.type === "user_message") {
            items.push({
              id: item.id,
              content: item.content,
              timestamp:
                item.pinToTop === true && Number.isFinite(taskCreatedTimestamp)
                  ? taskCreatedTimestamp
                  : item.timestamp,
            });
          }
          return items;
        },
        [],
      ),
    });
  }, [task, messages, commentThreads, conversationItems]);

  // A stretch of rows each saying "1 commit pushed" reads as noise and buries everything
  // else, so neighbours that said the same thing collapse into one row.
  const rows = useMemo(() => groupActivityRows(timelineRows), [timelineRows]);

  // Numbering a run and deciding whether to number it at all have to come from the same
  // population, or a task with three runs and one row labels that row "run 1".
  const runStartedCount = useMemo(
    () =>
      timelineRows.reduce(
        (count, row) =>
          row.kind === "event" && row.event.kind === "run_started"
            ? count + 1
            : count,
        0,
      ),
    [timelineRows],
  );

  const threadsById = useMemo(() => {
    const byId = new Map<string, TaskCommentThreadSummary>();
    for (const thread of commentThreads) byId.set(thread.id, thread);
    return byId;
  }, [commentThreads]);

  const focusThread = (thread: TaskCommentThreadSummary) => {
    if (!canOpenInPlace) return undefined;
    return () =>
      requestCommentFocus(
        task.id,
        // The scope/itemId pair the comment stores; `task` scope points at the task itself.
        thread.target.type === "task"
          ? { scope: "task", itemId: task.id }
          : {
              scope:
                thread.target.type === "canvas"
                  ? "desktop_canvas"
                  : "task_artifact",
              itemId: thread.target.id,
            },
        thread.id,
      );
  };

  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const openArtifact = (payload: ArtifactPayload) => {
    if (!canOpenInPlace || !payload.runId || !payload.artifactId) {
      return undefined;
    }
    const runId = payload.runId;
    return () =>
      openArtifactTab(task.id, {
        runId,
        artifactId: payload.artifactId,
        name: payload.name,
        objectKind: payload.objectKind ?? undefined,
      });
  };

  const openCommentThread = (payload: CommentEventPayload) => {
    if (!canOpenInPlace) return undefined;
    const scope = payload.scope;
    if (
      scope !== "task" &&
      scope !== "task_artifact" &&
      scope !== "desktop_canvas"
    ) {
      return undefined;
    }
    const itemId = scope === "task" ? task.id : payload.itemId;
    if (!itemId) return undefined;
    return () =>
      requestCommentFocus(task.id, { scope, itemId }, payload.rootCommentId);
  };

  const hasTranscript = useHasTranscriptListener(task.id);
  const requestScrollToMessage = useThreadNavigationStore(
    (state) => state.requestScrollToMessage,
  );
  const setActiveTab = usePanelLayoutStore((state) => state.setActiveTab);
  const chatPanelId = usePanelLayoutStore((state) => {
    const tree = state.taskLayouts[task.id]?.panelTree;
    if (!tree) return null;
    return findTabInTree(tree, DEFAULT_TAB_IDS.LOGS)?.panelId ?? null;
  });

  /**
   * Offered on prompt rows only. A prompt is the one item both panes share, so the jump names
   * its own target. Every other row is a thread message, a comment or a task field, none of
   * which the transcript renders, and the nearest prompt is not what the reader clicked.
   */
  const showPromptInChat = (promptId: string) => {
    if (!hasTranscript) return undefined;
    return () => {
      // The transcript's tab stays mounted while hidden, so without this the scroll happens
      // off screen and the click reads as doing nothing.
      if (chatPanelId) setActiveTab(task.id, chatPanelId, DEFAULT_TAB_IDS.LOGS);
      requestScrollToMessage(task.id, promptId);
    };
  };

  const renderRow = (
    row: GroupedActivityRow<TaskThreadMessage>,
    connectedAbove: boolean,
    connectedBelow: boolean,
  ) => {
    switch (row.kind) {
      case "event_group":
        return (
          <GroupedEventRow
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
            events={row.events}
            timestamp={new Date(row.ts).toISOString()}
          />
        );
      case "task_created":
        return (
          <TimelineRow
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
            gutter={<PersonBead user={task.created_by} badge={CREATED_BADGE} />}
            timestamp={task.created_at}
          >
            {`${task.created_by ? userDisplayName(task.created_by) : "Someone"} created this task`}
          </TimelineRow>
        );
      case "user_message":
        return (
          <UserMessageRow
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
            author={task.created_by}
            content={row.item.content}
            timestamp={new Date(row.item.timestamp).toISOString()}
            onShowInChat={showPromptInChat(row.item.id)}
          />
        );
      case "human_message":
        return (
          <ThreadReplyRow
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
            author={row.message.author}
            content={row.message.content}
            timestamp={row.message.created_at}
          />
        );
      case "event": {
        if (
          row.event.kind === "comment_added" ||
          row.event.kind === "comment_state_changed"
        ) {
          return (
            <CommentEventRow
              connectedAbove={connectedAbove}
              connectedBelow={connectedBelow}
              event={row.event}
              author={row.message.author ?? null}
              timestamp={row.message.created_at}
              taskId={task.id}
              onOpenThread={openCommentThread(row.event.payload)}
            />
          );
        }
        // A canvas or pull request announcement keeps its card, as the row's detail: every
        // row in the panel opens the same way.
        const artifactRow = messageRows.get(row.message.id);
        return (
          <ActivityEventRow
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
            event={row.event}
            timestamp={row.message.created_at}
            runCount={runStartedCount}
            runOrdinal={row.runOrdinal}
            detail={
              artifactRow?.kind === "artifact" ? (
                <ThreadArtifactCard
                  artifact={artifactRow.artifact}
                  openInPlaceTaskId={canOpenInPlace ? task.id : undefined}
                />
              ) : row.event.kind === "artifact_created" ||
                row.event.kind === "artifact_revised" ? (
                <ArtifactEventDetail
                  payload={row.event.payload}
                  onOpen={openArtifact(row.event.payload)}
                  taskId={canOpenInPlace ? task.id : undefined}
                />
              ) : undefined
            }
          />
        );
      }
      case "comment": {
        const thread = threadsById.get(row.thread.id);
        if (!thread) return null;
        return (
          <CommentRow
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
            thread={thread}
            isMentioned={
              !!currentUserId &&
              (thread.mentioned_user_ids ?? []).includes(currentUserId)
            }
            onSelect={focusThread(thread)}
          />
        );
      }
      case "comment_state": {
        const thread = threadsById.get(row.thread.id);
        if (!thread) return null;
        return (
          <CommentStateRow
            thread={thread}
            state={row.state}
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
          />
        );
      }
      case "run_output_pr":
        return (
          <ActivityEventRow
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
            event={{
              kind: "pr_created",
              payload: {
                prUrl: row.prUrl,
                repository: null,
                prNumber: null,
                actor: null,
              },
            }}
            timestamp={task.updated_at}
            runCount={runStartedCount}
            detail={
              <ThreadArtifactCard
                artifact={{ kind: "pr", url: row.prUrl }}
                openInPlaceTaskId={canOpenInPlace ? task.id : undefined}
              />
            }
          />
        );
      case "run_status":
        return (
          <RunStatusRow
            status={row.status}
            timestamp={task.updated_at}
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
          />
        );
    }
  };

  return (
    <div className="px-1 py-2">
      <ThreadItemGroup>
        {rows.map((row, index) => (
          <Fragment key={row.key}>
            {renderRow(row, index > 0, index < rows.length - 1)}
          </Fragment>
        ))}
      </ThreadItemGroup>
    </div>
  );
}
