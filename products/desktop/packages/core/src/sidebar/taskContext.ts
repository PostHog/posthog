import {
  CUSTOM_IMAGES_GROUP_NAME,
  findGroupFolder,
  type GroupableFolder,
} from "./groupTasks";
import type { TaskData } from "./sidebarData.types";

/** The `TaskData` fields a context line reads. */
export type TaskContextTask = Pick<
  TaskData,
  | "repository"
  | "originProduct"
  | "workspaceMode"
  | "branchName"
  | "linkedBranch"
>;

/** A registered folder, plus the display name the group header would use. */
export interface TaskContextFolder extends GroupableFolder {
  name: string;
}

function repositoryLabel(
  task: TaskContextTask,
  folders: TaskContextFolder[],
): string | null {
  if (task.originProduct === "image_builder") return CUSTOM_IMAGES_GROUP_NAME;
  const repository = task.repository;
  if (!repository) return null;
  // Prefer the registered folder's name so the line reads exactly like the
  // group header this task would sit under in "by-project" mode.
  return findGroupFolder(folders, repository.fullPath)?.name ?? repository.name;
}

function branchLabel(task: TaskContextTask): string | null {
  // `linkedBranch` is the branch the task produced, and is deliberately left
  // unset while a task sits on the repo's default branch — so this never
  // degrades into a "· main" that repeats on every row. A worktree falls back
  // to its checked-out branch, which is the whole reason the worktree exists.
  if (task.linkedBranch) return task.linkedBranch;
  return task.workspaceMode === "worktree" ? task.branchName : null;
}

/**
 * "Where does this task live" line for a task row rendered outside its
 * repository group — today the pinned section, which floats above the per-repo
 * groups and so loses the context its group header would have given it.
 *
 * Reads as `<repository> · <branch>`, dropping either half when unknown, and
 * returns null when the task has no repository or branch to report at all.
 */
export function formatTaskContext(
  task: TaskContextTask,
  folders: TaskContextFolder[] = [],
): string | null {
  const repository = repositoryLabel(task, folders);
  const branch = branchLabel(task);
  if (repository && branch) return `${repository} · ${branch}`;
  return repository ?? branch;
}
