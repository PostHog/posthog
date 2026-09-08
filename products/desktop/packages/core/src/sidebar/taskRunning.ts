import type { TaskData } from "./sidebarData.types";

// Drives the "Archive running task?" confirmation. An interactive cloud run can
// stay in_progress while it waits for input, so its status does not prove work.
export function isTaskActivelyRunning(
  task: Pick<
    TaskData,
    "isGenerating" | "runMode" | "taskRunEnvironment" | "taskRunStatus"
  >,
): boolean {
  if (task.isGenerating) return true;
  if (task.taskRunEnvironment !== "cloud") return false;
  if (task.taskRunStatus === "not_started" || task.taskRunStatus === "queued") {
    return true;
  }
  return task.taskRunStatus === "in_progress" && task.runMode === "background";
}
