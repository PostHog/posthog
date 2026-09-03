import {
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { buildChannelItems } from "@posthog/core/canvas/channelItems";
import {
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import type { ChannelItemActions } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { ChannelItemsPane } from "@posthog/ui/features/canvas/components/ChannelItemsPane";
import { FeedQueryHighlight } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { SavedSearchSwitcher } from "@posthog/ui/features/canvas/components/SavedSearchSwitcher";
import { useChannelSessionFacts } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useProjectTaskFeed } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useSavedSearchActions } from "@posthog/ui/features/canvas/hooks/useSavedSearchActions";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import {
  useTaskFeedSelection,
  useTaskFeedSelectionStore,
} from "@posthog/ui/features/canvas/stores/taskFeedSelectionStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useMemo } from "react";

export function TaskFeedPane({
  feedId,
  className,
}: {
  feedId: string;
  className?: string;
}) {
  const feed = useProjectTaskFeed(feedId);
  const select = useTaskFeedSelectionStore((state) => state.select);
  const selected = useTaskFeedSelection(feedId);
  const { error, errorMessage, isLoading, tasks } = useTaskFeedResults(
    feed?.query,
  );
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds, togglePin, setPinnedMany } = usePinnedTasks();
  const { archiveTask } = useArchiveTask();
  const sessionFacts = useChannelSessionFacts();
  const { openEdit, requestDelete, dialogs } = useSavedSearchActions(feed);

  const items = useMemo(
    () =>
      buildChannelItems({
        dashboards: [],
        feedTasks: tasks,
        archivedTaskIds,
        pinnedTaskIds,
        ownedBy: null,
        sessionFacts,
      }),
    [tasks, archivedTaskIds, pinnedTaskIds, sessionFacts],
  );

  const actions = useMemo<ChannelItemActions>(
    () => ({
      open: (item) =>
        select({
          feedId,
          taskId: item.id,
          channelId: item.task?.channel ?? null,
        }),
      togglePin: (item) => {
        togglePin(item.id).catch(() => toast.error("Couldn't update pin"));
      },
      setPinned: (pinItems, pinned) => {
        setPinnedMany(
          pinItems.map((item) => item.id),
          pinned,
        ).catch(() => toast.error("Couldn't update pin"));
      },
      archive: (item) => {
        void archiveTask({ taskId: item.id });
      },
    }),
    [feedId, select, togglePin, setPinnedMany, archiveTask],
  );

  useEffect(() => {
    track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
      action_type: "open",
      surface: "feed_home",
      feed_id: feedId,
    });
  }, [feedId]);

  if (!feed) {
    return (
      <div className={cn("flex min-h-0 flex-col", className)}>
        <Empty className="border-0 py-8">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <MagnifyingGlassIcon />
            </EmptyMedia>
            <EmptyTitle>Saved search not found</EmptyTitle>
            <EmptyDescription>
              Searches are saved per project on this device.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    );
  }

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex h-10 shrink-0 items-center gap-2 border-border border-b pr-2 pl-3">
        <SavedSearchSwitcher
          currentFeedId={feedId}
          className="min-w-0 flex-1"
        />
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Edit saved search"
            onClick={openEdit}
          >
            <PencilSimpleIcon size={14} />
          </Button>
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Delete saved search…"
            onClick={requestDelete}
          >
            <TrashIcon size={14} />
          </Button>
        </div>
      </div>

      <Button
        variant="default"
        left
        className="h-auto shrink-0 gap-2 rounded-none border-border border-b px-3 py-2"
        onClick={openEdit}
      >
        <FeedQueryHighlight query={feed.query} className="min-w-0 truncate" />
      </Button>

      {error ? (
        <Text className="block px-2 py-6 text-center text-(--red-11) text-xs">
          {errorMessage}
        </Text>
      ) : (
        <ChannelItemsPane
          items={items}
          isLoading={isLoading}
          actions={actions}
          activeKey={selected?.taskId ? `task:${selected.taskId}` : null}
          surface="saved_search"
          channelIdFor={(item) => item.task?.channel ?? undefined}
          emptyState={
            <Empty className="border-0 py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <MagnifyingGlassIcon />
                </EmptyMedia>
                <EmptyTitle>No tasks match</EmptyTitle>
                <EmptyDescription>
                  Tasks appear here as they start matching the query.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          }
        />
      )}

      {dialogs}
    </div>
  );
}
