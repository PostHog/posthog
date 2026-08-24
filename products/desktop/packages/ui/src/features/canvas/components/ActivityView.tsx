import {
  BellIcon,
  CheckIcon,
  ChecksIcon,
  LinkIcon,
  RobotIcon,
} from "@phosphor-icons/react";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import {
  Avatar,
  AvatarFallback,
  Badge,
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { UserBasic } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ActivityUnreadsToggle } from "@posthog/ui/features/canvas/components/ActivityUnreadsToggle";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { openActivityItem } from "@posthog/ui/features/canvas/components/openActivityItem";
import { useBlockedTaskIds } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { DOT_TONE_VAR } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect, useMemo } from "react";
import {
  activityReadPayload,
  getUnreadActivityItems,
  markLoadedReadLabel,
} from "./activityFeed";
import { activityMetadata } from "./activityMetadata";

export function ActivityRow({
  item,
  channelId,
  onOpen,
  onMarkRead,
  currentUser,
  blockedTaskIds,
  surface = "activity",
  onActivate,
  isSelected = false,
  compact = false,
}: {
  item: TaskActivityItem;
  /** Backend channel id (the /website route param); null when the task is unfiled. */
  channelId: string | null;
  onOpen: (item: TaskActivityItem) => void;
  onMarkRead: (item: TaskActivityItem) => void;
  currentUser?: UserBasic | null;
  /**
   * Tasks whose session is waiting on you. Passed in rather than selected here:
   * the feed renders one of these per item, and the selector behind it scans and
   * sorts every live session on each store notification.
   */
  blockedTaskIds: ReadonlySet<string>;
  surface?: "activity" | "activity_panel";
  /** Where the row goes is the feed's business, not the row's. */
  onActivate: (item: TaskActivityItem) => void;
  isSelected?: boolean;
  compact?: boolean;
}) {
  const isAgentActivity =
    item.activityKind === "awaiting_input" ||
    item.activityKind === "completed" ||
    (item.activityKind === "message" && !item.author);
  // The one row here that is blocked on you, and the sidebar's session rows
  // already say that in blue. Yellow is everything else the feed carries:
  // something happened that you haven't read.
  //
  // Read against the live sessions rather than the row's kind alone, so this is
  // the same fact the sidebar's blue dot is drawn from. The row records that the
  // agent asked at a moment in time; whether it is still waiting is a question
  // only the session can answer, and answering the prompt has to clear the dot.
  const awaitsReply =
    item.activityKind === "awaiting_input" && blockedTaskIds.has(item.taskId);
  const openTask = () => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "open_task",
      surface,
      channel_id: channelId ?? undefined,
      task_id: item.taskId,
    });
    onOpen(item);
    if (item.commentId && item.commentTarget) {
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(item.taskId, item.commentTarget, item.commentId);
    }
    onActivate(item);
  };

  return (
    <div className="group relative">
      <Button
        type="button"
        onClick={openTask}
        left
        className={`h-auto w-full text-left ${compact ? "py-1.5 pr-10" : "py-2"} ${isSelected ? "bg-fill-selected" : item.isUnread ? "bg-primary/10 outline outline-primary/20 hover:bg-primary/15" : ""}`}
      >
        <span className="relative mt-0.5 shrink-0">
          {isAgentActivity ? (
            <Avatar size="xs">
              <AvatarFallback>
                <RobotIcon size={12} />
              </AvatarFallback>
            </Avatar>
          ) : (
            <UserAvatar user={item.author ?? currentUser} size="xs" />
          )}
          {/* Unread is a fact about the feed: you haven't looked at this yet.
              Waiting on you is a fact about the session, and reading the row
              doesn't answer the prompt — so it keeps its dot until you do. */}
          {(item.isUnread || awaitsReply) && (
            <span
              className="-top-0.5 -right-0.5 absolute h-2 w-2 rounded-full"
              // Off the table the status dots read, so a row that says the agent
              // is waiting is the same blue as the session it is waiting in.
              style={{
                backgroundColor: awaitsReply
                  ? DOT_TONE_VAR.blue
                  : "var(--primary)",
              }}
              title={awaitsReply ? "Waiting on you" : "New activity"}
            />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span
              className={`truncate text-sm ${item.isUnread ? "font-semibold" : "font-medium"}`}
            >
              {item.taskTitle}
            </span>
            {item.isUnread && !compact && <Badge variant="info">New</Badge>}
          </span>
          <span className="block truncate text-muted-foreground text-xs">
            {activityMetadata(item, currentUser?.email)}
          </span>
          {item.snippet && !compact && (
            <MentionText
              content={item.snippet}
              currentUserEmail={currentUser?.email}
              className="mt-1 block whitespace-pre-wrap break-words text-xs"
            />
          )}
        </span>
      </Button>
      {item.isUnread && (
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Mark as read"
          title="Mark as read"
          className={`absolute opacity-0 transition-opacity group-hover:opacity-100 ${compact ? "right-2 bottom-1" : `top-2 ${channelId ? "right-9" : "right-2"}`}`}
          onClick={() => onMarkRead(item)}
        >
          <CheckIcon size={14} />
        </Button>
      )}
      {channelId && !compact && (
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Copy thread link"
          className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={() =>
            void copyChannelLink(channelId, "activity", item.taskId)
          }
        >
          <LinkIcon size={14} />
        </Button>
      )}
    </div>
  );
}

// The Activity page for the code layout: every task the viewer is involved in —
// created, mentioned in, or messaged in — newest activity first. Rows clear as
// they are opened, not when the page is; merely landing here shouldn't dismiss
// what you haven't read.
//
// The spaces layout has no page: the feed is the column beside the rail
// (ChannelsSidebar) and /activity's pane is whatever you picked from it.
export function ActivityView() {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const {
    items,
    unreadCount,
    isLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useTaskActivity();
  // Selected once for the feed, not once per row.
  const blockedTaskIds = useBlockedTaskIds();
  const { mutate: markTasksRead, isPending: isMarkingRead } =
    useMarkTaskActivityRead();
  const visibleItems = items;
  const unreadItems = useMemo(
    () => getUnreadActivityItems(visibleItems),
    [visibleItems],
  );
  const unreadsOnly = useActivityFilterStore((state) => state.unreadsOnly);
  const shownItems = unreadsOnly ? unreadItems : visibleItems;
  const visibleUnreadCount = unreadCount;
  // Opening a row is what marks it read. The server does the same when the task is
  // reached any other way, so the feed converges either way.
  const markRead = useCallback(
    (item: TaskActivityItem) =>
      markTasksRead([
        {
          task_id: item.taskId,
          seen_before: item.activityAt,
          ...(item.commentId ? { activity_id: item.id } : {}),
        },
      ]),
    [markTasksRead],
  );
  const markAllRead = useCallback(() => {
    markTasksRead(activityReadPayload(unreadItems));
  }, [markTasksRead, unreadItems]);
  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_activity",
      surface: "activity",
    });
  }, []);

  const markAllReadButton = (
    <Button
      variant="default"
      size="sm"
      loading={isMarkingRead}
      disabled={isMarkingRead}
      onClick={markAllRead}
    >
      <ChecksIcon size={14} />
      {markLoadedReadLabel(unreadItems.length, visibleUnreadCount)}
    </Button>
  );

  // Sits below the rows and below the empty state alike: filtering to unreads can
  // empty a page that still has unread activity waiting on the next one.
  const loadMoreButton = hasNextPage && (
    <div className="mt-3 flex justify-center">
      <Button
        variant="outline"
        loading={isFetchingNextPage}
        disabled={isFetchingNextPage}
        onClick={() => void fetchNextPage()}
      >
        Load more
      </Button>
    </div>
  );

  // The feed body is identical in both shells; only the empty-state copy tracks
  // the layout's naming ("spaces" vs "channels").
  const feed =
    isLoading && shownItems.length === 0 ? (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    ) : shownItems.length === 0 ? (
      <>
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BellIcon size={20} />
            </EmptyMedia>
            <EmptyTitle>
              {unreadsOnly ? "No unread activity" : "No activity yet"}
            </EmptyTitle>
            <EmptyDescription>
              {unreadsOnly
                ? "You're all caught up."
                : "Task updates and comment notifications across channels appear here."}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
        {loadMoreButton}
      </>
    ) : (
      <>
        <div className="flex flex-col gap-0.5">
          {shownItems.map((item) => (
            <ActivityRow
              key={item.id}
              item={item}
              channelId={item.channelId}
              onOpen={markRead}
              onMarkRead={markRead}
              onActivate={openActivityItem}
              currentUser={currentUser}
              blockedTaskIds={blockedTaskIds}
            />
          ))}
        </div>
        {loadMoreButton}
      </>
    );

  return (
    <div className="h-full overflow-y-auto bg-gray-1">
      <div className="mx-auto w-full max-w-[680px] px-4 py-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-bold text-2xl">Activity</h1>
            <p className="text-muted-foreground text-sm">
              Task updates and comment notifications across channels.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {unreadCount > 0 && markAllReadButton}
            <ActivityUnreadsToggle />
          </div>
        </div>
        <div className="mt-4">{feed}</div>
      </div>
    </div>
  );
}
