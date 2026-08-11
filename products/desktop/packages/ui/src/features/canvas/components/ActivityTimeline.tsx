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
  cn,
  ThreadItem,
  ThreadItemAuthor,
  ThreadItemBody,
  ThreadItemContent,
  ThreadItemGroup,
  ThreadItemGutter,
  ThreadItemHeader,
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
  RunStatusRow,
  TimelineRow,
} from "@posthog/ui/features/canvas/components/activityRows";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import {
  ThreadArtifactRow,
  ThreadMessageRow,
} from "@posthog/ui/features/canvas/components/ThreadPanel";
import { ThreadTimestamp } from "@posthog/ui/features/canvas/components/ThreadTimestamp";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import type { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { extractChannelContext } from "@posthog/ui/features/sessions/components/session-update/channelContext";
import { extractCustomInstructions } from "@posthog/ui/features/sessions/components/session-update/customInstructions";
import { useThreadNavigationStore } from "@posthog/ui/features/sessions/threadNavigationStore";
import { Fragment, type KeyboardEvent, useMemo } from "react";

type ConversationItem = ReturnType<
  typeof buildConversationItems
>["items"][number];

function UserMessageRow({
  author,
  content,
  timestamp,
  onSelect,
}: {
  author?: UserBasic | null;
  content: string;
  timestamp: string;
  /** Jumps the transcript to this message. Absent once the run is unavailable. */
  onSelect?: () => void;
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
  // The row itself is the hit target. `ThreadItem` renders an <article>, which a
  // <button> may not wrap and which can't become one (quill's primitive takes no
  // `render`), so it carries the button role and its own key handling.
  //
  // Deliberately no `aria-label`: the button takes its name from its contents, so
  // it announces the author, time and preview a sighted user sees. A label would
  // replace all three — and since every row here is authored by the task creator,
  // one built from the name alone would be identical on every row.
  const activation = onSelect
    ? ({
        role: "button",
        tabIndex: 0,
        onClick: onSelect,
        onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          onSelect();
        },
      } as const)
    : {};
  return (
    <ThreadItem
      className={cn("rounded-none", onSelect && "cursor-pointer")}
      {...activation}
    >
      {/* Decorative: the author's name is written beside it, so keep the avatar's
          initials out of the row's accessible name. */}
      <ThreadItemGutter className="justify-center" aria-hidden>
        <UserAvatar user={author} size="sm" className="sticky top-2" />
      </ThreadItemGutter>
      <ThreadItemContent>
        <ThreadItemHeader>
          <ThreadItemAuthor className="text-[13px]">{name}</ThreadItemAuthor>
          <ThreadTimestamp dateTime={timestamp} />
        </ThreadItemHeader>
        <ThreadItemBody className="mt-1.5 whitespace-pre-wrap break-words text-[13px]">
          <MentionText content={displayContent} />
          {channelContext && (
            <Collapsible className="mt-2 min-w-0 bg-transparent hover:bg-transparent data-open:bg-transparent">
              <CollapsibleTrigger
                className="min-h-0 w-full bg-transparent px-0 py-1 text-left hover:bg-transparent aria-expanded:bg-transparent"
                onClick={(event) => event.stopPropagation()}
                onKeyDown={(event) => event.stopPropagation()}
              >
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
        </ThreadItemBody>
      </ThreadItemContent>
    </ThreadItem>
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
  currentUserUuid,
  currentUserEmail,
  isTaskAuthor,
  canForward,
  canOpenInPlace,
  runCount = 1,
  onSendToAgent,
  onDelete,
}: {
  task: Task;
  timeline: ThreadTimelineRow<TaskThreadMessage>[];
  conversationItems: ConversationItem[];
  /** The task's comment threads, already collapsed one row per thread by the backend. */
  commentThreads?: TaskCommentThreadSummary[];
  commentsEnabled?: boolean;
  /** Needed to tell a mention of you from a mention of someone else. */
  currentUserId?: number;
  currentUserUuid?: string;
  currentUserEmail?: string | null;
  isTaskAuthor: boolean;
  canForward: boolean;
  /** True when the task's transcript and review pane are mounted beside this
   *  pane. False in the channel-home sidebar, where there is nothing to drive —
   *  rows there stay inert and PRs open externally instead of dead-clicking. */
  canOpenInPlace?: boolean;
  /** How many runs the task has; a single-run task shouldn't label its run. */
  runCount?: number;
  onSendToAgent: (messageId: string) => void;
  onDelete: (messageId: string) => void;
}) {
  const requestScrollToMessage = useThreadNavigationStore(
    (state) => state.requestScrollToMessage,
  );
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

  const renderRow = (row: ActivityRow<TaskThreadMessage>) => {
    switch (row.kind) {
      case "task_created":
        return (
          <TimelineRow
            gutter={
              <span className="relative z-10 flex size-6 items-center justify-center rounded-full bg-gray-3">
                <PlusCircleIcon
                  size={14}
                  weight="fill"
                  className="text-gray-11"
                />
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
            author={task.created_by}
            content={row.item.content}
            timestamp={new Date(row.item.timestamp).toISOString()}
            onSelect={
              canOpenInPlace
                ? () => requestScrollToMessage(task.id, row.item.id)
                : undefined
            }
          />
        );
      case "human_message":
        return (
          <ThreadMessageRow
            message={row.message}
            isTaskAuthor={isTaskAuthor}
            isOwnMessage={
              !!currentUserUuid && currentUserUuid === row.message.author?.uuid
            }
            currentUserEmail={currentUserEmail}
            canForward={canForward}
            preview
            onSendToAgent={() => onSendToAgent(row.message.id)}
            onDelete={() => onDelete(row.message.id)}
          />
        );
      case "event": {
        // Canvases and pull requests already have a card row; the rest read as one line.
        const artifactRow = messageRows.get(row.message.id);
        if (artifactRow?.kind === "artifact") {
          return (
            <ThreadArtifactRow
              artifact={artifactRow.artifact}
              createdAt={row.message.created_at}
              openInPlaceTaskId={canOpenInPlace ? task.id : undefined}
            />
          );
        }
        return (
          <ActivityEventRow
            event={row.event}
            timestamp={row.message.created_at}
            runCount={runCount}
            runOrdinal={row.runOrdinal}
          />
        );
      }
      case "comment": {
        const thread = threadsById.get(row.thread.id);
        if (!thread) return null;
        return (
          <CommentRow
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
            onSelect={focusThread(thread)}
          />
        );
      }
      case "run_status":
        return <RunStatusRow status={row.status} timestamp={task.updated_at} />;
    }
  };

  return (
    <div className="relative">
      {/* Every row centers its node in a 2.5rem gutter inset by the row's
          0.5rem padding, so the line runs through 0.5 + 2.5/2 = 1.75rem. */}
      <div
        aria-hidden
        className="pointer-events-none absolute top-4 bottom-4 left-[1.75rem] w-px bg-border"
      />
      <div className="relative z-10">
        <ThreadItemGroup>
          {rows.map((row) => (
            <Fragment key={row.key}>{renderRow(row)}</Fragment>
          ))}
        </ThreadItemGroup>
      </div>
    </div>
  );
}
