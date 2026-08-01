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
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { UserBasic } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
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
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { Text } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { memo, useCallback, useEffect, useMemo } from "react";
import {
  activityReadPayload,
  channelIdForName,
  createChannelIdByName,
  getUnreadActivityItems,
  markLoadedReadLabel,
} from "./activityFeed";

function ChannelSuffix({ channelName }: { channelName: string | null }) {
  if (!channelName) return null;
  return (
    <>
      {" in "}
      <Text as="span" size="1" weight="medium">
        #{channelName}
      </Text>
    </>
  );
}

/** The lead line describing what happened, chosen by the row's activity kind. */
export function activityHeadline(
  item: TaskActivityItem,
  currentUserEmail?: string | null,
): ReactNode {
  switch (item.activityKind) {
    case "awaiting_input":
      return (
        <>
          The agent is waiting for your reply
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "completed":
      return (
        <>
          The agent completed this task
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "message":
      if (!item.author) {
        return (
          <>
            The agent replied
            <ChannelSuffix channelName={item.channelName} />
          </>
        );
      }
      return (
        <>
          {item.author.email === currentUserEmail
            ? "You replied"
            : `${userDisplayName(item.author)} replied`}
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "mention":
      return (
        <>
          <Text as="span" size="1" weight="medium">
            {userDisplayName(item.author)}
          </Text>{" "}
          mentioned you
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    default:
      return "You created this task";
  }
}

export function ActivityRow({
  item,
  folderChannelId,
  onOpen,
  onMarkRead,
  currentUser,
  surface = "activity",
  onNavigate,
  compact = false,
}: {
  item: TaskActivityItem;
  /** Desktop folder channel id (the /website route param); null when unmapped. */
  folderChannelId: string | null;
  onOpen: (item: TaskActivityItem) => void;
  onMarkRead: (item: TaskActivityItem) => void;
  currentUser?: UserBasic | null;
  surface?: "activity" | "activity_panel";
  onNavigate?: () => void;
  compact?: boolean;
}) {
  const isAgentActivity =
    item.activityKind === "awaiting_input" ||
    item.activityKind === "completed" ||
    (item.activityKind === "message" && !item.author);
  const openTask = () => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "open_task",
      surface,
      channel_id: folderChannelId ?? undefined,
      task_id: item.taskId,
    });
    onOpen(item);
    onNavigate?.();
    // The channel thread route is the deep-link target; tasks whose channel
    // folder is gone fall back to the plain task view.
    if (folderChannelId) {
      navigateToChannelTask(folderChannelId, item.taskId);
    } else {
      navigateToTaskDetail(item.taskId);
    }
  };

  return (
    <div className="group relative">
      <button
        type="button"
        onClick={openTask}
        className={`flex w-full gap-2 rounded-md px-2 text-left transition-colors hover:bg-fill-hover ${compact ? "py-1.5 pr-14" : "py-2"} ${item.isUnread ? "bg-fill-secondary" : ""}`}
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
          {item.isUnread && (
            <span
              className="-top-0.5 -right-0.5 absolute h-2 w-2 rounded-full bg-primary"
              title="New activity"
            />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <Text
              size="1"
              weight={item.isUnread ? "medium" : "regular"}
              className="truncate"
            >
              {activityHeadline(item, currentUser?.email)}
            </Text>
            {item.isUnread && !compact && <Badge variant="info">New</Badge>}
            {!compact && (
              <Text size="1" className="shrink-0 text-muted-foreground">
                {formatRelativeTimeShort(item.activityAt)}
              </Text>
            )}
          </span>
          <Text size="1" className="block truncate text-muted-foreground">
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
      </button>
      {compact && (
        <Text
          size="1"
          className="pointer-events-none absolute top-1.5 right-2 text-muted-foreground"
        >
          {formatRelativeTimeShort(item.activityAt)}
        </Text>
      )}
      {item.isUnread && (
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Mark as read"
          title="Mark as read"
          className={`absolute opacity-0 transition-opacity group-hover:opacity-100 ${compact ? "right-2 bottom-1" : `top-2 ${folderChannelId ? "right-9" : "right-2"}`}`}
          onClick={() => onMarkRead(item)}
        >
          <CheckIcon size={14} />
        </Button>
      )}
      {folderChannelId && !compact && (
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Copy thread link"
          className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={() =>
            void copyChannelLink(folderChannelId, "activity", item.taskId)
          }
        >
          <LinkIcon size={14} />
        </Button>
      )}
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
  const { mutate: markTasksRead, isPending: isMarkingRead } =
    useMarkTaskActivityRead();
  const unreadItems = useMemo(() => getUnreadActivityItems(items), [items]);
  // Opening a row is what marks it read. The server does the same when the task is
  // reached any other way, so the feed converges either way.
  const markRead = useCallback(
    (item: TaskActivityItem) =>
      markTasksRead([{ task_id: item.taskId, seen_before: item.activityAt }]),
    [markTasksRead],
  );
  const markAllRead = useCallback(() => {
    markTasksRead(activityReadPayload(unreadItems));
  }, [markTasksRead, unreadItems]);
  // Items carry backend channel names only; the desktop folder-channel id
  // (needed for /website navigation and copy-link) is resolved here, where
  // the single useChannels subscription lives.
  const { channels: folderChannels } = useChannels();
  const folderIdByName = useMemo(
    () => createChannelIdByName(folderChannels),
    [folderChannels],
  );
  const folderChannelIdFor = useCallback(
    (channelName: string | null): string | null =>
      channelIdForName(folderIdByName, channelName),
    [folderIdByName],
  );
  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_activity",
      surface: "activity",
    });
  }, []);

  const markAllReadButton = useMemo(
    () =>
      unreadCount > 0 ? (
        <Button
          variant="default"
          size="sm"
          loading={isMarkingRead}
          disabled={isMarkingRead}
          onClick={markAllRead}
        >
          <ChecksIcon size={14} />
          {markLoadedReadLabel(unreadItems.length, unreadCount)}
        </Button>
      ) : null,
    [unreadCount, unreadItems.length, isMarkingRead, markAllRead],
  );

  const feed = (
    <ActivityFeed
      items={items}
      isLoading={isLoading}
      spacesLayout={spacesLayout}
      folderChannelIdFor={folderChannelIdFor}
      markRead={markRead}
      currentUser={currentUser}
      hasNextPage={hasNextPage}
      isFetchingNextPage={isFetchingNextPage}
      fetchNextPage={fetchNextPage}
    />
  );

  // The shared page header ships with the spaces layout; without it the page
  // keeps the in-container title it has always had. Delete the legacy branch
  // when the layout flag graduates.
  if (!spacesLayout) {
    return (
      <div className="h-full overflow-y-auto bg-gray-1">
        <div className="mx-auto w-full max-w-[680px] px-4 py-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Text size="5" weight="bold" className="block">
                Activity
              </Text>
              <Text size="2" className="block text-muted-foreground">
                Tasks you're involved in across{" "}
                {spacesLayout ? "spaces" : "channels"}.
              </Text>
            </div>
            {markAllReadButton}
          </div>
          <div className="mt-4">{feed}</div>
        </div>
      </div>
    );
  }

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
            {markAllReadButton && (
              <PageHeaderActions>{markAllReadButton}</PageHeaderActions>
            )}
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            Tasks you're involved in across{" "}
            {spacesLayout ? "spaces" : "channels"}.
          </PageHeaderDescription>
        </PageHeaderHeading>
      </PageHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[680px] px-4 py-6">{feed}</div>
      </div>
    </div>
  );
}

/**
 * The feed body. A memo'd child rather than JSX built in the parent: the parent
 * picks between two page shells and returns early, and this way the branch it
 * doesn't take costs nothing.
 */
const ActivityFeed = memo(function ActivityFeed({
  items,
  isLoading,
  spacesLayout,
  folderChannelIdFor,
  markRead,
  currentUser,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: {
  items: TaskActivityItem[];
  isLoading: boolean;
  spacesLayout: boolean;
  folderChannelIdFor: (channelName: string | null) => string | null;
  markRead: (item: TaskActivityItem) => void;
  currentUser?: UserBasic | null;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
}) {
  if (isLoading && items.length === 0) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BellIcon size={20} />
          </EmptyMedia>
          <EmptyTitle>No activity yet</EmptyTitle>
          <EmptyDescription>
            Tasks you create, get tagged in, or reply to across{" "}
            {spacesLayout ? "spaces" : "channels"} land here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      {items.map((item) => (
        <ActivityRow
          key={item.taskId}
          item={item}
          folderChannelId={folderChannelIdFor(item.channelName)}
          onOpen={markRead}
          onMarkRead={markRead}
          currentUser={currentUser}
        />
      ))}
      {hasNextPage && (
        <Button
          variant="outline"
          className="mt-3 self-center"
          loading={isFetchingNextPage}
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
        >
          Load more
        </Button>
      )}
    </div>
  );
});
