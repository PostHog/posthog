import { FileTextIcon, ScrollIcon } from "@phosphor-icons/react";
import {
  type ActivityRow,
  buildActivityTimeline,
  type UserMessageLike,
} from "@posthog/core/canvas/activityTimeline";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
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
  CommentRow,
  CommentStateRow,
  CREATED_BADGE,
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

/** A prompt the task's author sent the agent. Collapsed like every other row: the first
 *  line on the row, the message and its context when opened. */
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
  // Every injected block the chat strips has to be stripped here too, or the raw XML
  // shows up in the timeline for anyone whose chat never showed it.
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
                    ? `#${channelContext.mention.name} `
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

/** Stable identity: an inline `= []` default is a new array on every render, which would
 *  rebuild the timeline on every render through the memo's dependency list. */
const NO_COMMENT_THREADS: TaskCommentThreadSummary[] = [];

export function ActivityTimeline({
  task,
  timeline,
  conversationItems,
  commentThreads = NO_COMMENT_THREADS,
  commentsEnabled = false,
  currentUserId,
  canOpenInPlace,
  runCount = 1,
}: {
  task: Task;
  timeline: ThreadTimelineRow<TaskThreadMessage>[];
  conversationItems: ConversationItem[];
  /** The task's comment threads, already collapsed one row per thread by the backend. */
  commentThreads?: TaskCommentThreadSummary[];
  commentsEnabled?: boolean;
  /** Needed to tell a mention of you from a mention of someone else. */
  currentUserId?: number;
  /** True when the task's transcript and review pane are mounted beside this
   *  pane. False in the channel-home sidebar, where there is nothing to drive —
   *  rows there stay inert and PRs open externally instead of dead-clicking. */
  canOpenInPlace?: boolean;
  /** How many runs the task has; a single-run task shouldn't label its run. */
  runCount?: number;
}) {
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );

  // Thread messages arrive as `timeline` rows (human messages and the artifact
  // announcements it already understands) plus the raw messages behind them, which carry
  // the event rows. Rebuilding the message list from `timeline` keeps this component's
  // props unchanged while the merge itself moves into core.
  const messages = useMemo(
    () => timeline.map((row) => row.message),
    [timeline],
  );
  const messageRows = useMemo(() => {
    const byId = new Map<string, ThreadTimelineRow<TaskThreadMessage>>();
    for (const row of timeline) byId.set(row.message.id, row);
    return byId;
  }, [timeline]);

  const rows = useMemo(
    () =>
      buildActivityTimeline({
        task: {
          id: task.id,
          createdAt: task.created_at,
          updatedAt: task.updated_at,
          latestRunId: task.latest_run?.id ?? null,
          latestRunStatus: task.latest_run?.status ?? null,
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
                timestamp: item.timestamp,
              });
            }
            return items;
          },
          [],
        ),
        commentsEnabled,
      }),
    [task, messages, commentThreads, conversationItems, commentsEnabled],
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
        // The target is the scope/itemId pair the comment stores; `task` scope points at
        // the task itself.
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

  const hasTranscript = useHasTranscriptListener(task.id);
  const requestScrollToMessage = useThreadNavigationStore(
    (state) => state.requestScrollToMessage,
  );

  /**
   * The jump into the chat, offered only by a row that *is* a chat row — a prompt, which
   * points at itself.
   *
   * Nothing else can point anywhere reliably. The transcript resolves a jump against its
   * top-level rows, and everything inside a turn is nested in one, so an agent-side target
   * scrolls nowhere at all; and an event row is stamped by the API rather than by the
   * session, so it has no transcript id to name in the first place. Landing every other
   * row on the nearest prompt was the alternative, and it put you somewhere that wasn't
   * what you clicked.
   */
  const showInChat = (promptId: string) => {
    if (!hasTranscript) return undefined;
    return () => requestScrollToMessage(task.id, promptId);
  };

  const renderRow = (
    row: ActivityRow<TaskThreadMessage>,
    connectedAbove: boolean,
    connectedBelow: boolean,
  ) => {
    switch (row.kind) {
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
            // A prompt is a transcript row, so it points at itself.
            onShowInChat={showInChat(row.item.id)}
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
        // A canvas or pull request announcement keeps its card, but as the row's detail:
        // every row in the panel opens the same way.
        const artifactRow = messageRows.get(row.message.id);
        return (
          <ActivityEventRow
            connectedAbove={connectedAbove}
            connectedBelow={connectedBelow}
            event={row.event}
            timestamp={row.message.created_at}
            runCount={runCount}
            runOrdinal={row.runOrdinal}
            detail={
              artifactRow?.kind === "artifact" ? (
                <ThreadArtifactCard
                  artifact={artifactRow.artifact}
                  openInPlaceTaskId={canOpenInPlace ? task.id : undefined}
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
