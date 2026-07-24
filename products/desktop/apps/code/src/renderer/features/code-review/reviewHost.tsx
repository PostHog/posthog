import WorkerUrl from "@pierre/diffs/worker/worker.js?worker&url";
import type { ReviewHost } from "@posthog/ui/features/code-review/reviewHost";
import { ChangesPanel } from "@posthog/ui/features/task-detail/components/ChangesPanel";

export const diffWorkerFactory = () =>
  new Worker(WorkerUrl, { type: "module" });

export const reviewHost: ReviewHost = {
  diffWorkerFactory,
  renderExpandedSidebar: (task) => (
    <ChangesPanel taskId={task.id} task={task} />
  ),
};
