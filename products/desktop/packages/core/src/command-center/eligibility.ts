import type { Task } from "@posthog/shared/domain-types";

export interface CellEligibilityInput {
  assignedIds: Set<string>;
  archivedIds: Set<string>;
  workspaceIds: { has(id: string): boolean };
}

export function isTaskEligibleForCell(
  task: Task,
  input: CellEligibilityInput,
): boolean {
  return (
    !input.assignedIds.has(task.id) &&
    !input.archivedIds.has(task.id) &&
    input.workspaceIds.has(task.id)
  );
}

export function workspaceIdSet(
  workspaces: Record<string, unknown> | undefined,
): { has(id: string): boolean } {
  return {
    has: (id: string) => Boolean(workspaces?.[id]),
  };
}

export function selectAvailableTasks(
  tasks: Task[],
  input: CellEligibilityInput,
): Task[] {
  return tasks.filter((task) => isTaskEligibleForCell(task, input));
}
