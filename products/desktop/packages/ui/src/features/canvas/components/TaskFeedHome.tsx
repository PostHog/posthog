import {
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { Button, Skeleton } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { ChannelBreadcrumb } from "@posthog/ui/features/canvas/components/ChannelBreadcrumb";
import { ChannelFeedView } from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { FeedQueryHighlight } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { TaskFeedModal } from "@posthog/ui/features/canvas/components/TaskFeedModal";
import { useProjectTaskFeed } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import type { ThreadPanelTab } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { openRightPanelSide } from "@posthog/ui/features/navigation/rightPanelSide";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { toast } from "@posthog/ui/primitives/toast";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { Heading, Text } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";

/**
 * A custom feed: the channel feed's card design over the tasks a saved query
 * matches, project-wide rather than one channel's. Read-only on purpose — a
 * feed is a lens over existing work, so there is no composer; cards open the
 * task in its own channel.
 */
export function TaskFeedHome({ feedId }: { feedId: string }) {
  const navigate = useNavigate();
  const feed = useProjectTaskFeed(feedId);
  const removeFeed = useTaskFeedsStore((s) => s.removeFeed);
  const { tasks, isLoading, issues } = useTaskFeedResults(feed?.query);
  const [editOpen, setEditOpen] = useState(false);

  // The id alone, not the feed object: edits replace the object, and an edit
  // is not a new open.
  const trackedFeedId = feed?.id;
  useEffect(() => {
    if (!trackedFeedId) return;
    track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
      action_type: "open",
      surface: "feed_home",
      feed_id: trackedFeedId,
    });
  }, [trackedFeedId]);

  useSetHeaderContent(
    useMemo(
      () => <ChannelBreadcrumb channelName={feed?.name ?? "Feed"} />,
      [feed?.name],
    ),
  );

  const handleOpenTask = useCallback((task: Task) => {
    void openTask(task, { channelId: task.channel ?? undefined });
  }, []);

  // No thread dock here — like the spaces layout, a chip opens the session
  // itself with the right panel on the chip's tab.
  const handleOpenThread = useCallback(
    (task: Task, tab?: ThreadPanelTab) => {
      if (tab) openRightPanelSide(tab, task.id);
      handleOpenTask(task);
    },
    [handleOpenTask],
  );

  const handleDelete = useCallback(() => {
    if (!feed) return;
    removeFeed(feed.id);
    track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
      action_type: "delete",
      surface: "feed_home",
      feed_id: feed.id,
    });
    toast.success("Saved search deleted");
    void navigate({ to: "/website" });
  }, [feed, removeFeed, navigate]);

  if (!feed) {
    return (
      <div className="flex h-full min-w-0 flex-col items-center justify-center gap-2 bg-gray-1 px-4 text-center">
        <Heading className="font-bold text-xl">Saved search not found</Heading>
        <Text className="max-w-md text-(--gray-9)">
          This saved search isn't in this project. Searches are saved per
          project on this device, so one saved in another project or on another
          device won't appear here.
        </Text>
      </div>
    );
  }

  // Pinned above the cards, sharing their width: what the feed is showing and
  // the two things you can do to it. Doubles as the header of the empty state.
  const queryBar = (
    <div className="mb-2 flex w-full items-center gap-2 rounded-xl border border-(--gray-4) bg-(--gray-2) px-4 py-3">
      <MagnifyingGlassIcon size={14} className="shrink-0 text-(--gray-9)" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 items-center gap-2">
          <FeedQueryHighlight query={feed.query} className="min-w-0 truncate" />
          {isLoading ? (
            <Skeleton className="h-3 w-12 shrink-0 self-center" />
          ) : (
            <span className="shrink-0 text-(--gray-9) text-xs">
              {tasks.length} {tasks.length === 1 ? "task" : "tasks"}
            </span>
          )}
        </div>
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
      <Button
        variant="outline"
        size="xs"
        onClick={() => setEditOpen(true)}
        aria-label="Edit saved search"
      >
        <PencilSimpleIcon size={12} />
        Edit
      </Button>
      <Button
        variant="outline"
        size="xs"
        onClick={handleDelete}
        aria-label="Delete saved search"
      >
        <TrashIcon size={12} />
        Delete
      </Button>
    </div>
  );

  // The empty message rides inside the intro (which always renders) so the
  // query bar stays put while the feed has nothing to show under it.
  const intro = (
    <div>
      {queryBar}
      {!isLoading && tasks.length === 0 && (
        <div className="flex flex-col items-center gap-1 px-4 py-16 text-center">
          <Text className="font-medium">No tasks match this search yet</Text>
          <Text className="text-(--gray-9) text-sm">
            New tasks appear here as soon as they match the query.
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
      <TaskFeedModal open={editOpen} onOpenChange={setEditOpen} feed={feed} />
    </div>
  );
}
