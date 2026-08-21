import { BellIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useActivityDetailStore } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { TaskDetail } from "@posthog/ui/features/task-detail/components/TaskDetail";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { pickFreshestTask } from "@posthog/ui/features/tasks/taskFreshness";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { TaskDetailSkeleton } from "@posthog/ui/router/routeSkeletons";
import { useQuery } from "@tanstack/react-query";
import { memo, useEffect } from "react";

/**
 * What the Activity destination shows beside its feed. The feed picks a row and
 * this renders that row's task, without a route: Activity is a place you read
 * from, and navigating to the task would take the feed you are reading off the
 * screen.
 */
function ActivityDetailPaneInner() {
  const selected = useActivityDetailStore((s) => s.selected);
  const taskId = selected?.taskId;
  const { data: tasks } = useTasks();
  const { channels } = useChannels();
  const { markAsViewed } = useTaskViewed();

  const { data: fetched } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: Boolean(taskId),
  });

  useEffect(() => {
    if (taskId) markAsViewed(taskId);
  }, [taskId, markAsViewed]);

  if (!selected || !taskId) {
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

  const task = pickFreshestTask(
    fetched,
    tasks?.find((t) => t.id === taskId),
  );
  if (!task) return <TaskDetailSkeleton />;

  const channelId = selected.channelId;
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

/**
 * Propless and memoized, which makes this a render barrier the way a route
 * component is one.
 *
 * The task it renders publishes the layout's title row through the header
 * store, and the layout subscribes to that store — so if every layout render
 * reached back into this subtree, one unstable value inside the task view would
 * close a loop between the two and blow the update depth. A route's Outlet
 * stops that; without a route, this has to.
 */
export const ActivityDetailPane = memo(ActivityDetailPaneInner);
