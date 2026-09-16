import {
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { Button, Heading, Skeleton, Text } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { ChannelFeedView } from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { FeedQueryHighlight } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { SavedSearchSwitcher } from "@posthog/ui/features/canvas/components/SavedSearchSwitcher";
import { useProjectTaskFeed } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useSavedSearchActions } from "@posthog/ui/features/canvas/hooks/useSavedSearchActions";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import type { ThreadPanelTab } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { openRightPanelSide } from "@posthog/ui/features/navigation/rightPanelSide";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect } from "react";

export function TaskFeedHome({ feedId }: { feedId: string }) {
  const feed = useProjectTaskFeed(feedId);
  const {
    canRetry,
    error,
    errorMessage,
    isComplete,
    isFetching,
    isLoading,
    issues,
    refetch,
    tasks,
  } = useTaskFeedResults(feed?.query);
  const { openEdit, requestDelete, dialogs } = useSavedSearchActions(feed);

  const trackedFeedId = feed?.id;
  useEffect(() => {
    if (!trackedFeedId) return;
    track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
      action_type: "open",
      surface: "feed_home",
      feed_id: trackedFeedId,
    });
  }, [trackedFeedId]);

  const handleOpenTask = useCallback((task: Task) => {
    void openTask(task, { channelId: task.channel ?? undefined });
  }, []);

  const handleOpenThread = useCallback(
    (task: Task, tab?: ThreadPanelTab) => {
      if (tab) openRightPanelSide(tab, task.id);
      handleOpenTask(task);
    },
    [handleOpenTask],
  );

  if (!feed) {
    return (
      <div className="flex h-full min-w-0 flex-col items-center justify-center gap-2 bg-gray-1 px-4 text-center">
        <Heading className="font-bold text-xl">Saved search not found</Heading>
        <Text className="max-w-md text-muted-foreground">
          This saved search is not in this project. Searches are saved per
          project on this device. A search saved in another project or on
          another device does not appear here.
        </Text>
      </div>
    );
  }

  const resultCount = tasks.length;

  const queryBar = (
    <div className="mb-2 flex w-full items-center gap-2 rounded-xl border border-(--gray-4) bg-(--gray-2) px-4 py-3">
      <MagnifyingGlassIcon size={14} className="shrink-0 text-(--gray-9)" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 items-center gap-2">
          <FeedQueryHighlight query={feed.query} className="min-w-0 truncate" />
          {isLoading ? (
            <Skeleton className="h-3 w-12 shrink-0 self-center" />
          ) : error ? (
            canRetry ? (
              <Button
                variant="link-muted"
                size="xs"
                loading={isFetching}
                disabled={isFetching}
                onClick={refetch}
              >
                Try again
              </Button>
            ) : null
          ) : (
            <span className="shrink-0 text-muted-foreground text-xs">
              {isComplete
                ? `${resultCount} ${resultCount === 1 ? "task" : "tasks"}`
                : "Partial results"}
            </span>
          )}
        </div>
        {error ? (
          <span className="text-(--red-11) text-xs">{errorMessage}</span>
        ) : (
          !isLoading &&
          !isComplete && (
            <span className="text-muted-foreground text-xs">
              Some matching tasks may not be shown.
            </span>
          )
        )}
        {issues.map((issue) => (
          <span
            key={`${issue.raw}-${issue.message}`}
            className={
              issue.kind === "unsupported"
                ? "text-(--amber-11) text-xs"
                : "text-(--red-11) text-xs"
            }
          >
            {issue.message}
          </span>
        ))}
      </div>
    </div>
  );

  const header = (
    <div className="mb-2 flex min-w-0 items-center gap-2">
      <SavedSearchSwitcher currentFeedId={feedId} className="min-w-0 flex-1" />
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <Button
          variant="outline"
          size="xs"
          onClick={openEdit}
          aria-label="Edit saved search"
        >
          <PencilSimpleIcon size={12} />
          Edit
        </Button>
        <Button
          variant="outline"
          size="xs"
          onClick={requestDelete}
          aria-label="Delete saved search…"
        >
          <TrashIcon size={12} />
          Delete…
        </Button>
      </div>
    </div>
  );

  const intro = (
    <div>
      {header}
      {queryBar}
      {!isLoading && !error && isComplete && resultCount === 0 && (
        <div className="flex flex-col items-center gap-1 px-4 py-16 text-center">
          <Text className="font-medium">No tasks match this saved search</Text>
          <Text className="text-muted-foreground text-sm">
            Tasks appear here when they match the query.
          </Text>
        </div>
      )}
    </div>
  );

  return (
    <div className="flex h-full min-w-0 bg-gray-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <ChannelFeedView
          channelId={feed.id}
          tasks={tasks}
          isLoading={isLoading}
          intro={intro}
          onOpenTask={handleOpenTask}
          onOpenThread={handleOpenThread}
        />
      </div>
      {dialogs}
    </div>
  );
}
