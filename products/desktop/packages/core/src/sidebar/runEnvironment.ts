import type { TaskData } from "./sidebarData.types";

/**
 * The workspace environment ("local" | "cloud") of the most recently active task
 * in a repo group that has actually run, or `undefined` when none has.
 */
export function mostRecentRunEnvironment(
  tasks: readonly TaskData[],
): "local" | "cloud" | undefined {
  let best: TaskData | undefined;
  for (const task of tasks) {
    if (!task.taskRunEnvironment) continue;
    if (!best || task.lastActivityAt > best.lastActivityAt) {
      best = task;
    }
  }
  return best?.taskRunEnvironment;
}
