import { BellIcon } from "@phosphor-icons/react";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  MenuLabel,
  Spinner,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ActivityActionsMenu } from "@posthog/ui/features/canvas/components/ActivityActionsMenu";
import { ActivityRow } from "@posthog/ui/features/canvas/components/ActivityRow";
import { ActivityUnreadsToggle } from "@posthog/ui/features/canvas/components/ActivityUnreadsToggle";
import { InboxActivityOverflowRow } from "@posthog/ui/features/canvas/components/InboxActivityOverflowRow";
import { InboxActivityRow } from "@posthog/ui/features/canvas/components/InboxActivityRow";
import { openActivityItem } from "@posthog/ui/features/canvas/components/openActivityItem";
import { useBlockedTaskIds } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useInboxActivityPreview } from "@posthog/ui/features/canvas/hooks/useInboxActivityPreview";
import { useLocalDayStart } from "@posthog/ui/features/canvas/hooks/useLocalDayStart";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { track } from "@posthog/ui/shell/analytics";
import { Fragment, useCallback, useEffect, useMemo } from "react";
import {
  activityFeedSourceDescription,
  activityReadPayload,
  deriveActivityFeedContent,
  groupActivityItemsByDay,
} from "./activityFeed";

// The Activity page for the code layout: every task the viewer is involved in —
// created, mentioned in, or messaged in — newest activity first. Rows clear as
// they are opened, not when the page is; merely landing here shouldn't dismiss
// what you haven't read.
//
// The spaces layout has no page: the feed is the column beside the rail
// (ChannelsSidebar) and /activity's pane is whatever you picked from it.
export function ActivityView() {
  const mentionsIncluded = useActivityFilterStore(
    (state) => state.mentionsEnabled,
  );
  const unreadsOnly = useActivityFilterStore((state) => state.unreadsOnly);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({
    client,
    enabled: mentionsIncluded,
  });
  const taskActivity = useTaskActivity({ enabled: mentionsIncluded });
  const inboxActivity = useInboxActivityPreview();
  const {
    unreadItems,
    feedItems,
    lastShownReportId,
    remainingInboxReportCount,
    selfDrivingIncluded,
  } = useMemo(
    () =>
      deriveActivityFeedContent({
        taskItems: taskActivity.items,
        reports: inboxActivity.reports,
        totalReportCount: inboxActivity.totalCount,
        mentionsIncluded,
        reportsIncluded: inboxActivity.isIncluded,
        unreadsOnly,
      }),
    [
      taskActivity.items,
      inboxActivity.reports,
      inboxActivity.totalCount,
      inboxActivity.isIncluded,
      mentionsIncluded,
      unreadsOnly,
    ],
  );
  const unreadCount = mentionsIncluded ? taskActivity.unreadCount : 0;
  const isLoading =
    (mentionsIncluded && taskActivity.isLoading) ||
    (!unreadsOnly && inboxActivity.isLoading);
  // Selected once for the feed, not once per row.
  const blockedTaskIds = useBlockedTaskIds();
  const { mutate: markTasksRead, isPending: isMarkingRead } =
    useMarkTaskActivityRead();
  const dayStart = useLocalDayStart();
  const shownItemGroups = useMemo(
    () => groupActivityItemsByDay(feedItems, new Date(dayStart)),
    [feedItems, dayStart],
  );
  // Opening a row is what marks it read. The server does the same when the task is
  // reached any other way, so the feed converges either way.
  const markRead = useCallback(
    (item: TaskActivityItem) => markTasksRead(activityReadPayload([item])),
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

  // Sits below the rows and below the empty state alike: filtering to unreads can
  // empty a page that still has unread activity waiting on the next one.
  const loadMoreButton = mentionsIncluded && taskActivity.hasNextPage && (
    <div className="mt-3 flex justify-center">
      <Button
        variant="outline"
        loading={taskActivity.isFetchingNextPage}
        disabled={taskActivity.isFetchingNextPage}
        onClick={() => void taskActivity.fetchNextPage()}
      >
        Load more
      </Button>
    </div>
  );

  // The feed body is identical in both shells; only the empty-state copy tracks
  // the layout's naming ("spaces" vs "channels").
  const feed =
    isLoading && feedItems.length === 0 ? (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    ) : feedItems.length === 0 ? (
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
                : activityFeedSourceDescription(
                    mentionsIncluded,
                    selfDrivingIncluded,
                  )}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
        {loadMoreButton}
      </>
    ) : (
      <>
        <div className="flex flex-col gap-0.5">
          {shownItemGroups.map((group) => (
            <Fragment key={group.key}>
              <MenuLabel>{group.label}</MenuLabel>
              {group.items.map((item) => (
                <Fragment key={item.id}>
                  {item.kind === "task" ? (
                    <ActivityRow
                      item={item.task}
                      onMarkRead={markRead}
                      onActivate={openActivityItem}
                      currentUser={currentUser}
                      blockedTaskIds={blockedTaskIds}
                    />
                  ) : (
                    <InboxActivityRow report={item.report} />
                  )}
                  {item.kind === "report" &&
                    item.report.id === lastShownReportId &&
                    remainingInboxReportCount > 0 && (
                      <InboxActivityOverflowRow
                        count={remainingInboxReportCount}
                      />
                    )}
                </Fragment>
              ))}
            </Fragment>
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
              {activityFeedSourceDescription(
                mentionsIncluded,
                selfDrivingIncluded,
              )}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <ActivityUnreadsToggle />
            <ActivityActionsMenu
              loadedUnreadCount={unreadItems.length}
              totalUnreadCount={unreadCount}
              isMarkingRead={isMarkingRead}
              onMarkAllRead={markAllRead}
            />
          </div>
        </div>
        <div className="mt-4">{feed}</div>
      </div>
    </div>
  );
}
