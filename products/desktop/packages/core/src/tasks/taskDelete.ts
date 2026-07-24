interface IdentifiableTask {
  id: string;
}

interface FocusSessionLike {
  worktreePath?: string | null;
}

interface WorkspaceLike {
  worktreePath?: string | null;
  folderPath?: string;
}

export function shouldUnfocusBeforeDelete(
  focusSession: FocusSessionLike | null | undefined,
  workspace: WorkspaceLike | null | undefined,
): boolean {
  if (!workspace?.worktreePath) {
    return false;
  }
  return focusSession?.worktreePath === workspace.worktreePath;
}

export function removeTaskFromList<T extends IdentifiableTask>(
  tasks: T[] | undefined,
  taskId: string,
): T[] | undefined {
  return tasks?.filter((task) => task.id !== taskId);
}

export function insertTaskDedup<T extends IdentifiableTask>(
  tasks: T[] | undefined,
  newTask: T,
): T[] | undefined {
  if (!tasks) return tasks;
  if (tasks.some((task) => task.id === newTask.id)) return tasks;
  return [newTask, ...tasks];
}

export function shouldNavigateAwayFromDeletedTask(
  view: { type: string; data?: { id?: string } | null } | undefined,
  taskId: string,
): boolean {
  return view?.type === "task-detail" && view.data?.id === taskId;
}
