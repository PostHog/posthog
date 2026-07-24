import type { Task } from "@posthog/shared/domain-types";

export interface WorktreeEntryData {
  worktreePath: string;
  head: string;
  branch: string | null;
  taskIds: string[];
}

export interface WorktreeGroupData {
  folderPath: string;
  worktrees: WorktreeEntryData[];
}

export interface FolderLike {
  path: string;
}

export function groupWorktrees(
  folders: readonly FolderLike[],
  worktreesByFolderIndex: readonly (readonly WorktreeEntryData[] | undefined)[],
): WorktreeGroupData[] {
  const groups: WorktreeGroupData[] = [];

  for (let i = 0; i < folders.length; i++) {
    const folder = folders[i];
    const worktrees = worktreesByFolderIndex[i];

    if (!worktrees || worktrees.length === 0) continue;

    groups.push({
      folderPath: folder.path,
      worktrees: worktrees.map((wt) => ({
        worktreePath: wt.worktreePath,
        head: wt.head,
        branch: wt.branch,
        taskIds: wt.taskIds,
      })),
    });
  }

  return groups.sort((a, b) => a.folderPath.localeCompare(b.folderPath));
}

export function buildTaskMap(
  tasks: readonly Task[] | undefined,
): Map<string, Task> {
  const map = new Map<string, Task>();
  if (tasks) {
    for (const task of tasks) {
      map.set(task.id, task);
    }
  }
  return map;
}

export function parseWorktreeLimit(rawValue: string): number | null {
  const value = Number.parseInt(rawValue, 10);
  return value >= 1 ? value : null;
}
