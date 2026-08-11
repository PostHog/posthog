import { FileTextIcon, PlusCircleIcon } from "@phosphor-icons/react";
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
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import {
  ActivityEventRow,
  CommentRow,
  CommentStateRow,
  DetailBlock,
  RunStatusRow,
  ThreadReplyRow,
  TimelineRow,
} from "@posthog/ui/features/canvas/components/activityRows";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { ThreadArtifactCard } from "@posthog/ui/features/canvas/components/ThreadPanel";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import type { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { extractChannelContext } from "@posthog/ui/features/sessions/components/session-update/channelContext";
import { extractCustomInstructions } from "@posthog/ui/features/sessions/components/session-update/customInstructions";
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
  connected,
}: {
  author?: UserBasic | null;
  content: string;
  timestamp: string;
  connected: boolean;
}) {
  const name = author ? userDisplayName(author) : "You";
  const channelContext = useMemo(
    () => extractChannelContext(content),
    [content],
  );
  const afterChannelContext = channelContext?.stripped ?? content;
  const customInstructions = useMemo(
    () => extractCustomInstructions(afterChannelContext),
    [afterChannelContext],
  );
  const displayContent = customInstructions?.stripped ?? afterChannelContext;
  const trimmed = displayContent.trim();
  const firstLine = trimmed.split("\n", 1)[0] ?? "";
  return (
    <TimelineRow
      connected={connected}
      gutter={
        // Decorative: the author's name is written beside it, so keep the avatar's
        // initials out of the row's accessible name.
        <div
          aria-hidden
          className="relative z-10 flex size-5 items-center justify-center overflow-hidden rounded-full border border-gray-7 ring-4 ring-gray-1"
        >
          <UserAvatar user={author} size="sm" className="size-5" />
        </div>
      }
      timestamp={timestamp}
      detail={
        <div className="space-y-1.5">
          <DetailBlock>
            <div className="whitespace-pre-wrap break-words">
              <MentionText content={displayContent} />
            </div>
          </DetailBlock>
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

  const renderRow = (
    row: ActivityRow<TaskThreadMessage>,
    connected: boolean,
  ) => {
    switch (row.kind) {
      case "task_created":
        return (
          <TimelineRow
            connected={connected}
            gutter={
              <span className="relative z-10 flex size-5 items-center justify-center rounded-full border border-gray-7 bg-gray-5 text-gray-12 ring-4 ring-gray-1">
                <PlusCircleIcon size={11} weight="fill" />
              </span>
            }
            timestamp={task.created_at}
          >
            {`${task.created_by ? userDisplayName(task.created_by) : "Someone"} created this task`}
          </TimelineRow>
        );
      case "user_message":
        return (
          <UserMessageRow
            connected={connected}
            author={task.created_by}
            content={row.item.content}
            timestamp={new Date(row.item.timestamp).toISOString()}
          />
        );
      case "human_message":
        return (
          <ThreadReplyRow
            connected={connected}
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
            connected={connected}
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
            connected={connected}
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
            connected={connected}
          />
        );
      }
      case "run_status":
        return (
          <RunStatusRow
            status={row.status}
            timestamp={task.updated_at}
            connected={connected}
          />
        );
    }
  };

  return (
    <div className="px-1 py-2">
      <ThreadItemGroup>
        {rows.map((row, index) => (
          <Fragment key={row.key}>
            {renderRow(row, index < rows.length - 1)}
          </Fragment>
        ))}
      </ThreadItemGroup>
    </div>
  );
}
