import { isTerminalStatus } from "@posthog/shared/domain-types";
import type { TaskData } from "./sidebarData.types";

// Drives the "Archive running task?" confirmation. Persisted run status is only
// trustworthy for cloud runs; local runs stay "in_progress" forever (nothing
// writes a terminal status when the agent goes idle), so a local run counts as
// running only while a prompt is in flight (isGenerating).
export function isTaskActivelyRunning(task: TaskData): boolean {
  if (task.isGenerating) return true;
  return (
    task.taskRunEnvironment === "cloud" &&
    task.taskRunStatus !== undefined &&
    !isTerminalStatus(task.taskRunStatus)
  );
}
