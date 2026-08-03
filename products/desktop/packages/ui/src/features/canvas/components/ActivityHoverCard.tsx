import { BellIcon, ChecksIcon } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  PopoverContent,
  Spinner,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ActivityRow } from "@posthog/ui/features/canvas/components/ActivityView";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useMemo, useState } from "react";
import {
  activityReadPayload,
  channelIdForName,
  createChannelIdByName,
  getUnreadActivityItems,
  markLoadedReadLabel,
} from "./activityFeed";

interface ActivityHoverCardProps {
  onClose: () => void;
  side?: "bottom" | "right";
}

export function ActivityHoverCard({
  onClose,
  side = "right",
}: ActivityHoverCardProps) {
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
  const [scrollRoot, setScrollRoot] = useState<HTMLDivElement | null>(null);
  const [loadMoreRef, loadMoreInView] = useInView<HTMLDivElement>({
    root: scrollRoot,
    rootMargin: "100px 0px",
  });
  const unreadItems = getUnreadActivityItems(items);
  const { mutate: markTasksRead, isPending: isMarkingRead } =
    useMarkTaskActivityRead();
  const { channels } = useChannels();
  const folderIdByName = useMemo(
    () => createChannelIdByName(channels),
    [channels],
  );
  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_activity",
      surface: "activity_panel",
    });
  }, []);
  useEffect(() => {
    if (loadMoreInView && hasNextPage) {
      void fetchNextPage();
    }
  }, [fetchNextPage, hasNextPage, loadMoreInView]);

  const markRead = (taskId: string, activityAt: string) => {
    markTasksRead([{ task_id: taskId, seen_before: activityAt }]);
  };

  const markAllRead = () => {
    markTasksRead(activityReadPayload(unreadItems));
  };

  return (
    <PopoverContent
      side={side}
      align="start"
      sideOffset={8}
      className="w-[380px] gap-0 overflow-hidden p-0"
    >
      <div className="flex min-h-12 items-center justify-between border-border border-b px-3">
        <span className="font-semibold text-sm">Activity</span>
        {unreadItems.length > 0 && (
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
        )}
      </div>
      <div ref={setScrollRoot} className="max-h-[480px] overflow-y-auto p-1.5">
        {isLoading && items.length === 0 ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : items.length === 0 ? (
          <Empty className="border-0 py-8">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BellIcon />
              </EmptyMedia>
              <EmptyTitle>No recent activity</EmptyTitle>
              <EmptyDescription>
                New task updates will appear here.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex flex-col gap-0.5">
            {items.map((item) => (
              <ActivityRow
                key={item.taskId}
                item={item}
                folderChannelId={channelIdForName(
                  folderIdByName,
                  item.channelName,
                )}
                onOpen={(activity) =>
                  markRead(activity.taskId, activity.activityAt)
                }
                onMarkRead={(activity) =>
                  markRead(activity.taskId, activity.activityAt)
                }
                currentUser={currentUser}
                surface="activity_panel"
                onNavigate={onClose}
                compact
              />
            ))}
          </div>
        )}
        <div ref={loadMoreRef} className="flex h-8 justify-center py-2">
          {hasNextPage && isFetchingNextPage && <Spinner />}
        </div>
      </div>
    </PopoverContent>
  );
}
