import { BellIcon } from "@phosphor-icons/react";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import {
  Autocomplete,
  AutocompleteList,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  MenuLabel,
  Spinner,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { ActivityActionsMenu } from "@posthog/ui/features/canvas/components/ActivityActionsMenu";
import { ActivityRow } from "@posthog/ui/features/canvas/components/ActivityRow";
import { ActivityUnreadsToggle } from "@posthog/ui/features/canvas/components/ActivityUnreadsToggle";
import { InboxActivityOverflowRow } from "@posthog/ui/features/canvas/components/InboxActivityOverflowRow";
import { InboxActivityRow } from "@posthog/ui/features/canvas/components/InboxActivityRow";
import { openActivityItem } from "@posthog/ui/features/canvas/components/openActivityItem";
import { SidebarSearchHeader } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import { useBlockedTaskIds } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useInboxActivityPreview } from "@posthog/ui/features/canvas/hooks/useInboxActivityPreview";
import { useLocalDayStart } from "@posthog/ui/features/canvas/hooks/useLocalDayStart";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { track } from "@posthog/ui/shell/analytics";
import { Fragment, useEffect, useMemo, useState } from "react";
import {
  activityFeedSourceDescription,
  activityReadPayload,
  deriveActivityFeedContent,
  filterActivityFeedItems,
  groupActivityItemsByDay,
} from "./activityFeed";

interface ActivityFeedListProps {
  onActivate?: (item: TaskActivityItem) => void;
  onReportActivate?: (report: SignalReport) => void;
  onOpened?: () => void;
  selectedId?: string;
  className?: string;
}

/** The feed's header and scrolling list, drawn by both the rail's pane and the
 *  code layout's hover card. */
export function ActivityFeedList({
  onActivate = openActivityItem,
  onReportActivate,
  onOpened,
  selectedId,
  className,
}: ActivityFeedListProps) {
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
  const [scrollRoot, setScrollRoot] = useState<HTMLDivElement | null>(null);
  const [query, setQuery] = useState("");
  const [loadMoreRef, loadMoreInView] = useInView<HTMLDivElement>({
    root: scrollRoot,
    rootMargin: "100px 0px",
  });
  const searchedFeedItems = useMemo(
    () => filterActivityFeedItems(feedItems, query),
    [feedItems, query],
  );
  const isSearching = query.trim() !== "";
  const dayStart = useLocalDayStart();
  const shownItemGroups = useMemo(
    () => groupActivityItemsByDay(searchedFeedItems, new Date(dayStart)),
    [searchedFeedItems, dayStart],
  );
  const overflowOptionValue = "activity:remaining-inbox-reports";
  const optionValues = searchedFeedItems.flatMap((item) => [
    item.id,
    ...(item.kind === "report" &&
    item.report.id === lastShownReportId &&
    remainingInboxReportCount > 0
      ? [overflowOptionValue]
      : []),
  ]);
  const { mutate: markTasksRead, isPending: isMarkingRead } =
    useMarkTaskActivityRead();
  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_activity",
      surface: "activity_panel",
    });
  }, []);
  useEffect(() => {
    if (mentionsIncluded && loadMoreInView && taskActivity.hasNextPage) {
      void taskActivity.fetchNextPage();
    }
  }, [
    mentionsIncluded,
    taskActivity.fetchNextPage,
    taskActivity.hasNextPage,
    loadMoreInView,
  ]);

  const markRead = (item: (typeof taskActivity.items)[number]) => {
    markTasksRead(activityReadPayload([item]));
  };

  const markAllRead = () => {
    markTasksRead(activityReadPayload(unreadItems));
  };

  return (
    <Autocomplete<string>
      inline
      open
      value={query}
      items={optionValues}
      filter={null}
      onValueChange={(value, eventDetails) => {
        if (
          eventDetails.reason === "input-change" &&
          typeof value === "string"
        ) {
          setQuery(value);
        }
      }}
    >
      <div className={cn("flex min-h-0 flex-col", className)}>
        <SidebarSearchHeader
          title="Activity"
          query={query}
          placeholder="Search activity…"
          searchLabel="Search activity"
          onClear={() => setQuery("")}
          actions={
            <>
              <ActivityUnreadsToggle />
              <ActivityActionsMenu
                loadedUnreadCount={unreadItems.length}
                totalUnreadCount={unreadCount}
                isMarkingRead={isMarkingRead}
                onMarkAllRead={markAllRead}
              />
            </>
          }
        />
        <AutocompleteList
          ref={setScrollRoot}
          className="sidebar-autocomplete-tree scroll-mask-8 !max-h-none !p-1.5 min-h-0 flex-1 overflow-y-auto"
        >
          {isLoading && feedItems.length === 0 ? (
            <div className="flex justify-center py-10">
              <Spinner />
            </div>
          ) : searchedFeedItems.length === 0 ? (
            <Empty className="border-0 py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BellIcon />
                </EmptyMedia>
                <EmptyTitle>
                  {isSearching
                    ? "No matching activity"
                    : unreadsOnly
                      ? "No unread activity"
                      : "No recent activity"}
                </EmptyTitle>
                <EmptyDescription>
                  {isSearching
                    ? "Try a different search."
                    : unreadsOnly
                      ? "You're all caught up."
                      : activityFeedSourceDescription(
                          mentionsIncluded,
                          selfDrivingIncluded,
                        )}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="flex flex-col gap-px">
              {shownItemGroups.map((group) => (
                <Fragment key={group.key}>
                  <MenuLabel>{group.label}</MenuLabel>
                  {group.items.map((item) => (
                    <Fragment key={item.id}>
                      {item.kind === "task" ? (
                        <ActivityRow
                          item={item.task}
                          onMarkRead={markRead}
                          currentUser={currentUser}
                          blockedTaskIds={blockedTaskIds}
                          surface="activity_panel"
                          onActivate={(activated) => {
                            onActivate(activated);
                            onOpened?.();
                          }}
                          isSelected={item.task.id === selectedId}
                          compact
                          asOption
                          optionValue={item.id}
                        />
                      ) : (
                        <InboxActivityRow
                          report={item.report}
                          onOpened={onOpened}
                          compact
                          asOption
                          optionValue={item.id}
                          onActivate={onReportActivate}
                          isSelected={item.report.id === selectedId}
                        />
                      )}
                      {item.kind === "report" &&
                        item.report.id === lastShownReportId &&
                        remainingInboxReportCount > 0 && (
                          <InboxActivityOverflowRow
                            count={remainingInboxReportCount}
                            onOpened={onOpened}
                            asOption
                            optionValue={overflowOptionValue}
                          />
                        )}
                    </Fragment>
                  ))}
                </Fragment>
              ))}
            </div>
          )}
          <div ref={loadMoreRef} className="flex h-8 justify-center py-2">
            {mentionsIncluded &&
              taskActivity.hasNextPage &&
              taskActivity.isFetchingNextPage && <Spinner />}
          </div>
        </AutocompleteList>
      </div>
    </Autocomplete>
  );
}
