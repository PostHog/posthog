import WorkerUrl from "@pierre/diffs/worker/worker.js?worker&url";
import type { ReviewHost } from "@posthog/ui/features/code-review/reviewHost";
import { ChangesPanel } from "@posthog/ui/features/task-detail/components/ChangesPanel";

// Diff rendering is pure browser code — a web worker over a Vite-resolved asset
// URL plus the ChangesPanel React component — so this mirrors the desktop
// renderer's reviewHost verbatim. ChangesPanel is cloud-aware (useIsCloudTask ->
// useCloudChangedFiles), so it renders a cloud task's diff without local git.
export const webDiffWorkerFactory = () =>
  new Worker(WorkerUrl, { type: "module" });

export const webReviewHost: ReviewHost = {
  diffWorkerFactory: webDiffWorkerFactory,
  renderExpandedSidebar: (task) => (
    <ChangesPanel taskId={task.id} task={task} />
  ),
};
