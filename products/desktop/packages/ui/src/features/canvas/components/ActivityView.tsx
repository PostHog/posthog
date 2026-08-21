import {
  BellIcon,
  CheckIcon,
  ChecksIcon,
  DotsThreeIcon,
  EnvelopeSimpleIcon,
  LinkIcon,
  RobotIcon,
} from "@phosphor-icons/react";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import {
  Avatar,
  AvatarFallback,
  Badge,
  Button,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Heading,
  Spinner,
  Text,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { UserBasic } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ActivityUnreadsToggle } from "@posthog/ui/features/canvas/components/ActivityUnreadsToggle";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { useBlockedTaskIds } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useMarkTaskActivityUnread } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityUnread";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { DOT_TONE_VAR } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import {
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect, useMemo } from "react";
import {
  activityReadPayload,
  getUnreadActivityItems,
  markLoadedReadLabel,
} from "./activityFeed";
import { activityHeadline } from "./activityHeadline";

export function ActivityRow({
  item,
  channelId,
  onOpen,
  onMarkRead,
  onMarkUnread,
  isUpdatingReadState = false,
  currentUser,
  blockedTaskIds,
  surface = "activity",
  onNavigate,
  compact = false,
}: {
  item: TaskActivityItem;
  /** Backend channel id (the /website route param); null when the task is unfiled. */
  channelId: string | null;
  onOpen: (item: TaskActivityItem) => void;
  onMarkRead: (item: TaskActivityItem) => void;
  onMarkUnread: (item: TaskActivityItem) => void;
  isUpdatingReadState?: boolean;
  currentUser?: UserBasic | null;
  /**
   * Tasks whose session is waiting on you. Passed in rather than selected here:
   * the feed renders one of these per item, and the selector behind it scans and
   * sorts every live session on each store notification.
   */
  blockedTaskIds: ReadonlySet<string>;
  surface?: "activity" | "activity_panel";
  onNavigate?: () => void;
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
    onNavigate?.();
    if (channelId && item.commentTarget?.scope === "desktop_canvas") {
      useCanvasChatPanelStore.getState().openComments();
      navigateToChannelDashboard(channelId, item.commentTarget.itemId);
      return;
    }
    // The channel thread route is the deep-link target; unfiled tasks fall
    // back to the plain task view.
    if (channelId) {
      if (item.commentId) {
        useThreadPanelStore.getState().setCollapsed(false);
      }
      navigateToChannelTask(channelId, item.taskId);
    } else {
      navigateToTaskDetail(item.taskId);
    }
  };

  return (
    <div className="group relative">
      <ContextMenu>
        <ContextMenuTrigger
          render={
            <button
              type="button"
              onClick={openTask}
              className={`flex w-full gap-2 rounded-md px-2 text-left transition-colors hover:bg-fill-hover ${compact ? "py-1.5 pr-14" : "py-2 pr-10"} ${item.isUnread ? "bg-fill-secondary" : ""}`}
            />
          }
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
              <Text
                size="xs"
                weight={item.isUnread ? "medium" : "normal"}
                className="truncate"
              >
                {activityHeadline(item, currentUser?.email)}
              </Text>
              {item.isUnread && !compact && <Badge variant="info">New</Badge>}
              {!compact && (
                <Text size="xs" className="shrink-0 text-muted-foreground">
                  {formatRelativeTimeShort(item.activityAt)}
                </Text>
              )}
            </span>
            <Text size="xs" className="block truncate text-muted-foreground">
              {item.taskTitle}
            </Text>
            {item.snippet && !compact && (
              <MentionText
                content={item.snippet}
                currentUserEmail={currentUser?.email}
                className="mt-1 block whitespace-pre-wrap break-words text-xs"
              />
            )}
          </span>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-48">
          {item.isUnread ? (
            <ContextMenuItem
              disabled={isUpdatingReadState}
              onClick={() => onMarkRead(item)}
            >
              <CheckIcon size={14} />
              Mark as read
            </ContextMenuItem>
          ) : (
            <ContextMenuItem
              disabled={isUpdatingReadState}
              onClick={() => onMarkUnread(item)}
            >
              <EnvelopeSimpleIcon size={14} />
              Mark as unread
            </ContextMenuItem>
          )}
          {channelId && (
            <>
              <ContextMenuSeparator />
              <ContextMenuItem
                onClick={() =>
                  void copyChannelLink(channelId, surface, item.taskId)
                }
              >
                <LinkIcon size={14} />
                Copy link
              </ContextMenuItem>
            </>
          )}
        </ContextMenuContent>
      </ContextMenu>
      {compact && (
        <Text
          size="xs"
          className="pointer-events-none absolute top-1.5 right-2 text-muted-foreground"
        >
          {formatRelativeTimeShort(item.activityAt)}
        </Text>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="default"
              size="icon-xs"
              aria-label={`More actions for ${item.taskTitle}`}
              data-attr="activity-item-menu"
              className={`absolute opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 ${compact ? "right-2 bottom-1" : "top-2 right-2"}`}
              onClick={(event) => event.stopPropagation()}
            />
          }
        >
          <DotsThreeIcon size={14} weight="bold" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          {item.isUnread ? (
            <DropdownMenuItem
              disabled={isUpdatingReadState}
              onClick={() => onMarkRead(item)}
            >
              <CheckIcon size={14} />
              Mark as read
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem
              disabled={isUpdatingReadState}
              onClick={() => onMarkUnread(item)}
            >
              <EnvelopeSimpleIcon size={14} />
              Mark as unread
            </DropdownMenuItem>
          )}
          {channelId && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() =>
                  void copyChannelLink(channelId, surface, item.taskId)
                }
              >
                <LinkIcon size={14} />
                Copy link
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

// The Activity page: every task the viewer is involved in — created, mentioned
// in, or messaged in — newest activity first. Rows clear as they are opened, not
// when the page is; merely landing here shouldn't dismiss what you haven't read.
export function ActivityView() {
  const spacesLayout = useChannelsLayout();
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
  const { mutate: markTasksUnread, isPending: isMarkingUnread } =
    useMarkTaskActivityUnread();
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
  const markReadFromMenu = useCallback(
    (item: TaskActivityItem) => {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "mark_activity_read",
        surface: "activity",
        channel_id: item.channelId ?? undefined,
        task_id: item.taskId,
      });
      markRead(item);
    },
    [markRead],
  );
  const markUnread = useCallback(
    (item: TaskActivityItem) => {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "mark_activity_unread",
        surface: "activity",
        channel_id: item.channelId ?? undefined,
        task_id: item.taskId,
      });
      markTasksUnread(activityReadPayload([item]));
    },
    [markTasksUnread],
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
                : `Task updates and comment notifications across ${spacesLayout ? "spaces" : "channels"} appear here.`}
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
              onMarkRead={markReadFromMenu}
              onMarkUnread={markUnread}
              isUpdatingReadState={isMarkingRead || isMarkingUnread}
              currentUser={currentUser}
              blockedTaskIds={blockedTaskIds}
            />
          ))}
        </div>
        {loadMoreButton}
      </>
    );

  if (spacesLayout) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-gray-1">
        <PageHeader>
          <PageHeaderHeading>
            <PageHeaderTitleRow>
              <PageHeaderTitle>Activity</PageHeaderTitle>
              {unreadCount > 0 && (
                <PageHeaderChip icon={<BellIcon size={12} weight="fill" />}>
                  {unreadCount} unread
                </PageHeaderChip>
              )}
              <PageHeaderActions>
                {unreadCount > 0 && markAllReadButton}
                <ActivityUnreadsToggle />
              </PageHeaderActions>
            </PageHeaderTitleRow>
            <PageHeaderDescription>
              Task updates and comment notifications across spaces.
            </PageHeaderDescription>
          </PageHeaderHeading>
        </PageHeader>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[680px] px-4 py-6">{feed}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-1">
      <div className="mx-auto w-full max-w-[680px] px-4 py-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <Heading size="xl" render={<h1 aria-label="Activity" />}>
              Activity
            </Heading>
            <Text size="sm" className="block text-muted-foreground">
              Task updates and comment notifications across{" "}
              {spacesLayout ? "spaces" : "channels"}.
            </Text>
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
