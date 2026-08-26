import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import {
  type ActivityFeedItem,
  getUnreadActivityItems,
  mergeActivityFeedItems,
} from "@posthog/ui/features/canvas/components/activityFeed";
import { useInboxActivityPreview } from "@posthog/ui/features/canvas/hooks/useInboxActivityPreview";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useMemo } from "react";

interface ActivityFeedState {
  items: TaskActivityItem[];
  unreadItems: TaskActivityItem[];
  unreadCount: number;
  feedItems: ActivityFeedItem[];
  lastShownReportId: string | undefined;
  remainingInboxReportCount: number;
  mentionsIncluded: boolean;
  selfDrivingIncluded: boolean;
  unreadsOnly: boolean;
  isLoading: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => Promise<unknown>;
}

export function useActivityFeed(): ActivityFeedState {
  const mentionsEnabled = useActivityFilterStore(
    (state) => state.mentionsEnabled,
  );
  const unreadsOnly = useActivityFilterStore((state) => state.unreadsOnly);
  const taskActivity = useTaskActivity({ enabled: mentionsEnabled });
  const inboxActivity = useInboxActivityPreview();
  const unreadItems = useMemo(
    () => getUnreadActivityItems(taskActivity.items),
    [taskActivity.items],
  );
  const feedItems = useMemo(
    () =>
      mergeActivityFeedItems(
        mentionsEnabled ? (unreadsOnly ? unreadItems : taskActivity.items) : [],
        unreadsOnly ? [] : inboxActivity.reports,
      ),
    [
      mentionsEnabled,
      unreadsOnly,
      unreadItems,
      taskActivity.items,
      inboxActivity.reports,
    ],
  );

  return {
    items: taskActivity.items,
    unreadItems,
    unreadCount: taskActivity.unreadCount,
    feedItems,
    lastShownReportId: unreadsOnly
      ? undefined
      : inboxActivity.reports.at(-1)?.id,
    remainingInboxReportCount: unreadsOnly
      ? 0
      : Math.max(0, inboxActivity.totalCount - inboxActivity.reports.length),
    mentionsIncluded: mentionsEnabled,
    selfDrivingIncluded: inboxActivity.isIncluded,
    unreadsOnly,
    isLoading:
      (mentionsEnabled && taskActivity.isLoading) ||
      (!unreadsOnly && inboxActivity.isLoading),
    hasNextPage: mentionsEnabled && taskActivity.hasNextPage,
    isFetchingNextPage: mentionsEnabled && taskActivity.isFetchingNextPage,
    fetchNextPage: taskActivity.fetchNextPage,
  };
}
