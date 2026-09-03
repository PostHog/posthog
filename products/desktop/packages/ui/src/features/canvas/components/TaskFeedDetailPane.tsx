import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useTaskFeedSelection } from "@posthog/ui/features/canvas/stores/taskFeedSelectionStore";
import { TaskDetail } from "@posthog/ui/features/task-detail/components/TaskDetail";
import { useResolvedTask } from "@posthog/ui/features/tasks/useResolvedTask";
import { TaskDetailSkeleton } from "@posthog/ui/router/routeSkeletons";

export function TaskFeedDetailPane({ feedId }: { feedId: string }) {
  const selected = useTaskFeedSelection(feedId);
  const task = useResolvedTask(selected?.taskId);
  const { channels } = useChannels();

  if (!selected) {
    return (
      <div className="flex h-full items-center justify-center">
        <Empty className="border-0">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <MagnifyingGlassIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing selected</EmptyTitle>
            <EmptyDescription>
              Pick a task from the search to read it here.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    );
  }

  if (!task) return <TaskDetailSkeleton />;

  const channelId = task.channel ?? selected.channelId ?? undefined;
  const channelName = channels.find((c) => c.id === channelId)?.name;

  return (
    <div className="h-full min-w-0">
      <TaskDetail
        task={task}
        channelName={channelName}
        channelId={channelName ? channelId : undefined}
      />
    </div>
  );
}
