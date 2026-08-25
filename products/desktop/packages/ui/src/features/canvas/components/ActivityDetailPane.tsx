import { BellIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useActivitySelection } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { TaskDetail } from "@posthog/ui/features/task-detail/components/TaskDetail";
import { useResolvedTask } from "@posthog/ui/features/tasks/useResolvedTask";
import { TaskDetailSkeleton } from "@posthog/ui/router/routeSkeletons";

/** What the Activity destination shows beside its feed. */
export function ActivityDetailPane() {
  const selected = useActivitySelection();
  const task = useResolvedTask(selected?.taskId);
  const { channels } = useChannels();

  if (!selected) {
    return (
      <div className="flex h-full items-center justify-center">
        <Empty className="border-0">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BellIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing selected</EmptyTitle>
            <EmptyDescription>
              Pick something from the feed to read it here.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    );
  }

  if (!task) return <TaskDetailSkeleton />;

  const { channelId } = selected;
  const channelName = channels.find((c) => c.id === channelId)?.name;

  return (
    <div className="h-full min-w-0">
      <TaskDetail
        task={task}
        channelName={channelName ?? "Space"}
        channelId={channelId ?? undefined}
      />
    </div>
  );
}
