import { readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";

export type TaskStatusPresentationKind =
  | "pr"
  | "completed"
  | "failed"
  | "running"
  | "started"
  | "chat";

export function getTaskStatusPresentationKind(
  task: Pick<Task, "latest_run">,
): TaskStatusPresentationKind {
  const latestRun = task.latest_run;

  if (readPrUrls(latestRun?.output)[0]) {
    return "pr";
  }

  if (latestRun?.environment === "cloud") {
    return "chat";
  }

  switch (latestRun?.status) {
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "in_progress":
      return "running";
    case "queued":
      return "started";
    default:
      return "chat";
  }
}
