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
import { ActivityUnreadsToggle } from "@posthog/ui/features/canvas/components/ActivityUnreadsToggle";
import { ActivityRow } from "@posthog/ui/features/canvas/components/ActivityView";
import { useBlockedTaskIds } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useCommentsEnabled } from "@posthog/ui/features/sessions/useCommentsEnabled";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef, useState } from "react";
import {
  activityReadPayload,
  activityUnreadTotalForLabel,
  getUnreadActivityItems,
  getVisibleActivityItems,
  markLoadedReadLabel,
} from "./activityFeed";

// How many pages the popover will pull looking for a row to show before it settles on the empty
// state. Enough to cover a page whose rows are all filtered out, short of paging a whole history.
const MAX_EMPTY_PAGES_TO_FILL = 3;

interface ActivityHoverCardProps {
  onClose: () => void;
  side?: "bottom" | "right";
}

export function ActivityHoverCard({
  onClose,
  side = "right",
}: ActivityHoverCardProps) {
  const commentsEnabled = useCommentsEnabled();
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
  const visibleItems = getVisibleActivityItems(items, commentsEnabled);
  const unreadItems = getUnreadActivityItems(visibleItems);
  const shownItems = unreadsOnly ? unreadItems : visibleItems;
  // An empty list with pages left is still filling rather than empty, so it shows the spinner
  // instead of claiming the viewer is caught up: the unread can be on the page still loading.
  // Bounded, because with the unreads filter on a caught-up viewer has no unread on any page,
  // and an unbounded sentinel would walk their whole activity history every time this opens.
  const emptyPagesFetched = useRef(0);
  const canFillFromNextPages =
    hasNextPage && emptyPagesFetched.current < MAX_EMPTY_PAGES_TO_FILL;
  const isFilling =
    shownItems.length === 0 && (isLoading || canFillFromNextPages);
  const { mutate: markTasksRead, isPending: isMarkingRead } =
    useMarkTaskActivityRead();
  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_activity",
      surface: "activity_panel",
    });
  }, []);
  useEffect(() => {
    if (!loadMoreInView || !hasNextPage) return;
    if (shownItems.length === 0) {
      if (emptyPagesFetched.current >= MAX_EMPTY_PAGES_TO_FILL) return;
      emptyPagesFetched.current += 1;
    } else {
      emptyPagesFetched.current = 0;
    }
    void fetchNextPage();
  }, [fetchNextPage, hasNextPage, loadMoreInView, shownItems.length]);

  const markRead = (item: (typeof items)[number]) => {
    markTasksRead(activityReadPayload([item]));
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
      <div className="flex min-h-12 items-center gap-2 border-border border-b px-3">
        <span className="font-semibold text-sm">Activity</span>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {unreadItems.length > 0 && (
            <Button
              variant="default"
              size="sm"
              loading={isMarkingRead}
              disabled={isMarkingRead}
              onClick={markAllRead}
            >
              <ChecksIcon size={14} />
              {markLoadedReadLabel(
                unreadItems.length,
                activityUnreadTotalForLabel({
                  commentsEnabled,
                  unreadCount,
                  loadedVisibleUnread: unreadItems.length,
                  hasNextPage,
                }),
              )}
            </Button>
          )}
          <ActivityUnreadsToggle />
        </div>
      </div>
      <div ref={setScrollRoot} className="max-h-[480px] overflow-y-auto p-1.5">
        {isFilling ? (
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
          <div className="flex flex-col gap-0.5">
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
