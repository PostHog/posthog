import { readPrUrls } from "@posthog/shared";
import type {
  Task,
  TaskRunEnvironment,
  TaskRunStatus,
  UserBasic,
} from "@posthog/shared/domain-types";

export type TaskStatusPresentationKind =
  | "pr"
  | "completed"
  | "failed"
  | "running"
  | "started"
  | "chat";

export function runStatusForDisplay({
  status,
  environment,
  runMode,
  isGenerating,
}: {
  status: TaskRunStatus | null | undefined;
  environment: TaskRunEnvironment | null | undefined;
  runMode?: "interactive" | "background" | null;
  isGenerating?: boolean;
}): TaskRunStatus | null {
  if (
    status === "in_progress" &&
    environment === "cloud" &&
    isGenerating === false &&
    runMode !== "background"
  ) {
    return null;
  }
  return status ?? null;
}

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

// Who to show a task under: only a task a person started names an author; an
// agent-made one would otherwise credit whoever the backend recorded.
export function taskStarter(task: Task): UserBasic | null {
  return task.origin_product === "user_created"
    ? (task.created_by ?? null)
    : null;
}
