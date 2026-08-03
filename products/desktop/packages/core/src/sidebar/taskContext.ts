import {
  CUSTOM_IMAGES_GROUP_NAME,
  findGroupFolder,
  type GroupableFolder,
} from "./groupTasks";
import type { TaskData } from "./sidebarData.types";

export type TaskContextTask = Pick<
  TaskData,
  | "repository"
  | "originProduct"
  | "workspaceMode"
  | "branchName"
  | "linkedBranch"
>;

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
  // The registered folder's name is what the group header shows. No collision
  // prefix here: pinned tasks are partitioned out before groups are built.
  return findGroupFolder(folders, repository.fullPath)?.name ?? repository.name;
}

function branchLabel(task: TaskContextTask): string | null {
  // `linkedBranch` stays unset while a task sits on the repo's default branch,
  // so rows never all repeat "· main". Worktrees fall back to their checkout.
  if (task.linkedBranch) return task.linkedBranch;
  return task.workspaceMode === "worktree" ? task.branchName : null;
}

/**
 * `<repository> · <branch>` line for a row rendered outside its repository
 * group (the pinned section), where no group header supplies the context.
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
