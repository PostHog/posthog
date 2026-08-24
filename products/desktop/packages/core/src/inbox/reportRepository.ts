import type { Task } from "@posthog/shared/domain-types";

/**
 * Resolve the repository a report's work happened in. Association is derived
 * from `task_run` artefacts — the repository is simply the first one any
 * associated task carries, walking oldest-first (repo selection / research
 * precede implementation).
 */
export async function resolveReportRepository(
  associatedTasks: Array<{ taskId: string; startedAt: string }>,
  getTask: (taskId: string) => Promise<Task | null>,
): Promise<string | null> {
  const ordered = [...associatedTasks].sort((a, b) =>
    a.startedAt.localeCompare(b.startedAt),
  );
  for (const entry of ordered) {
    const task = await getTask(entry.taskId);
    if (task?.repository) {
      return task.repository.toLowerCase();
    }
  }
  return null;
}
