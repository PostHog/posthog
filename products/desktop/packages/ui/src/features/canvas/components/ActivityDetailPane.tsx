import { BellIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useInboxActivityPreview } from "@posthog/ui/features/canvas/hooks/useInboxActivityPreview";
import { useActivitySelection } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { ReportDetail } from "@posthog/ui/features/inbox/components/ReportDetail";
import { TaskDetail } from "@posthog/ui/features/task-detail/components/TaskDetail";
import { useResolvedTask } from "@posthog/ui/features/tasks/useResolvedTask";
import { TaskDetailSkeleton } from "@posthog/ui/router/routeSkeletons";

/** What the Activity destination shows beside its feed. */
export function ActivityDetailPane() {
  const selected = useActivitySelection();
  const selectedTaskId =
    selected?.kind === "task" ? selected.taskId : undefined;
  const task = useResolvedTask(selectedTaskId);
  const { channels } = useChannels();
  const { reports } = useInboxActivityPreview();

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

  if (selected.kind === "report") {
    const cachedReport = reports.find(
      (report) => report.id === selected.reportId,
    );
    return (
      <div className="h-full min-w-0">
        <ReportDetail
          reportId={selected.reportId}
          cachedReport={cachedReport}
          backTo="/activity"
          backLabel="Back to activity"
          statusRedirect={false}
        />
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
