import {
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { FeedQueryHighlight } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { TaskFeedModal } from "@posthog/ui/features/canvas/components/TaskFeedModal";
import { useTaskStatusInput } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { useProjectTaskFeed } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import {
  useTaskFeedSelection,
  useTaskFeedSelectionStore,
} from "@posthog/ui/features/canvas/stores/taskFeedSelectionStore";
import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

function TaskFeedRow({
  task,
  isActive,
  onSelect,
}: {
  task: Task;
  isActive: boolean;
  onSelect: () => void;
}) {
  const status = useTaskStatusInput(task, { withPrStatus: false });

  return (
    <SidebarItem
      depth={0}
      icon={status ? <TaskStatusDot dot={taskDot(status)} /> : null}
      label={task.title}
      isActive={isActive}
      onClick={onSelect}
      endHint={
        <span className="text-muted-foreground text-xs">
          {formatRelativeTimeShort(task.last_activity_at ?? task.updated_at)}
        </span>
      }
    />
  );
}

export function TaskFeedPane({
  feedId,
  className,
}: {
  feedId: string;
  className?: string;
}) {
  const navigate = useNavigate();
  const feed = useProjectTaskFeed(feedId);
  const removeFeed = useTaskFeedsStore((state) => state.removeFeed);
  const select = useTaskFeedSelectionStore((state) => state.select);
  const selected = useTaskFeedSelection(feedId);
  const { error, errorMessage, isComplete, isLoading, tasks } =
    useTaskFeedResults(feed?.query);
  const [editOpen, setEditOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

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

  const handleDelete = () => {
    removeFeed(feed.id);
    select(null);
    track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
      action_type: "delete",
      surface: "feed_home",
      feed_id: feed.id,
    });
    toast.success("Saved search deleted");
    void navigate({ to: "/website" });
  };

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex h-10 shrink-0 items-center gap-2 border-border border-b pr-2 pl-3">
        <span className="truncate font-bold text-base">{feed.name}</span>
        {!isLoading && !error && (
          <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
            {isComplete ? tasks.length : `${tasks.length}+`}
          </span>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Edit saved search"
            onClick={() => setEditOpen(true)}
          >
            <PencilSimpleIcon size={14} />
          </Button>
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Delete saved search…"
            onClick={() => setConfirmDeleteOpen(true)}
          >
            <TrashIcon size={14} />
          </Button>
        </div>
      </div>

      <Button
        variant="default"
        left
        className="h-auto shrink-0 gap-2 rounded-none border-border border-b px-3 py-2"
        onClick={() => setEditOpen(true)}
      >
        <MagnifyingGlassIcon size={12} className="shrink-0 text-(--gray-9)" />
        <FeedQueryHighlight query={feed.query} className="min-w-0 truncate" />
      </Button>

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {isLoading && tasks.length === 0 ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : error ? (
          <Text className="block px-2 py-6 text-center text-(--red-11) text-xs">
            {errorMessage}
          </Text>
        ) : tasks.length === 0 ? (
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
        ) : (
          <div className="flex flex-col gap-px">
            {tasks.map((task) => (
              <TaskFeedRow
                key={task.id}
                task={task}
                isActive={selected?.taskId === task.id}
                onSelect={() =>
                  select({
                    feedId,
                    taskId: task.id,
                    channelId: task.channel ?? null,
                  })
                }
              />
            ))}
          </div>
        )}
      </div>

      <TaskFeedModal open={editOpen} onOpenChange={setEditOpen} feed={feed} />
      <AlertDialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete saved search?</AlertDialogTitle>
            <AlertDialogDescription>
              Delete <span className="font-medium">{feed.name}</span>? You
              cannot undo this action.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" size="sm">
                  Cancel
                </Button>
              }
            />
            <Button variant="destructive" size="sm" onClick={handleDelete}>
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
