import { BellIcon, ChecksIcon } from "@phosphor-icons/react";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import {
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ActivityUnreadsToggle } from "@posthog/ui/features/canvas/components/ActivityUnreadsToggle";
import { ActivityRow } from "@posthog/ui/features/canvas/components/ActivityView";
import { openActivityItem } from "@posthog/ui/features/canvas/components/openActivityItem";
import { useBlockedTaskIds } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useState } from "react";
import {
  activityReadPayload,
  getUnreadActivityItems,
  markLoadedReadLabel,
} from "./activityFeed";

interface ActivityFeedListProps {
  onActivate?: (item: TaskActivityItem) => void;
  onOpened?: () => void;
  selectedId?: string;
  className?: string;
}

/** The feed's header and scrolling list, drawn by both the rail's pane and the
 *  code layout's hover card. */
export function ActivityFeedList({
  onActivate = openActivityItem,
  onOpened,
  selectedId,
  className,
}: ActivityFeedListProps) {
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
  const [scrollRoot, setScrollRoot] = useState<HTMLDivElement | null>(null);
  const [loadMoreRef, loadMoreInView] = useInView<HTMLDivElement>({
    root: scrollRoot,
    rootMargin: "100px 0px",
  });
  const unreadsOnly = useActivityFilterStore((state) => state.unreadsOnly);
  const unreadItems = getUnreadActivityItems(items);
  const shownItems = unreadsOnly ? unreadItems : items;
  const { mutate: markTasksRead, isPending: isMarkingRead } =
    useMarkTaskActivityRead();
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

  const markRead = (item: (typeof items)[number]) => {
    markTasksRead(activityReadPayload([item]));
  };

  const markAllRead = () => {
    markTasksRead(activityReadPayload(unreadItems));
  };

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex h-10 shrink-0 items-center gap-2 border-border border-b pr-2 pl-3">
        <span className="font-bold text-base">Activity</span>
        <div className="ml-auto flex shrink-0 items-center gap-1">
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
          <ActivityUnreadsToggle />
        </div>
      </div>
      <div ref={setScrollRoot} className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {isLoading && shownItems.length === 0 ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : shownItems.length === 0 ? (
          <Empty className="border-0 py-8">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BellIcon />
              </EmptyMedia>
              <EmptyTitle>
                {unreadsOnly ? "No unread activity" : "No recent activity"}
              </EmptyTitle>
              <EmptyDescription>
                {unreadsOnly
                  ? "You're all caught up."
                  : "New task updates will appear here."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex flex-col gap-px">
            {shownItems.map((item) => (
              <ActivityRow
                key={item.id}
                item={item}
                channelId={item.channelId}
                onOpen={markRead}
                onMarkRead={markRead}
                currentUser={currentUser}
                blockedTaskIds={blockedTaskIds}
                surface="activity_panel"
                onActivate={(activated) => {
                  onActivate(activated);
                  onOpened?.();
                }}
                isSelected={item.id === selectedId}
                compact
              />
            ))}
          </div>
        )}
        <div ref={loadMoreRef} className="flex h-8 justify-center py-2">
          {hasNextPage && isFetchingNextPage && <Spinner />}
        </div>
      </div>
    </div>
  );
}
