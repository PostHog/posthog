import {
  getRelativeDateGroup,
  getTaskRepository,
  normalizeRepoKey,
  parseRepository,
} from "@posthog/shared";

export interface TaskRepositoryInfo {
  fullPath: string;
  name: string;
  organization?: string;
}

export interface GroupableTask {
  repository: TaskRepositoryInfo | null;
  originProduct?: string;
}

export const CUSTOM_IMAGES_GROUP_ID = "custom-images";

export interface TaskGroup<T extends GroupableTask> {
  id: string;
  name: string;
  tasks: T[];
}

export function getRepositoryInfo(
  task: { repository?: string | null },
  folderPath?: string,
): TaskRepositoryInfo | null {
  const repository = getTaskRepository(task);
  if (repository) {
    const normalized = normalizeRepoKey(repository);
    const parsed = parseRepository(normalized);
    if (parsed) {
      return {
        fullPath: normalized.toLowerCase(),
        name: parsed.repoName,
        organization: parsed.organization,
      };
    }
    // Malformed repository string (e.g. legacy single-segment values). Fall
    // through so the task lands in the folder-path or "other" bucket instead
    // of colliding with a real owner/repo group.
  }
  if (folderPath) {
    const name = folderPath.split("/").pop() ?? folderPath;
    return {
      fullPath: folderPath,
      name,
    };
  }
  return null;
}

export function folderGroupId(folder: {
  path: string;
  remoteUrl: string | null;
}): string {
  if (folder.remoteUrl) {
    return normalizeRepoKey(folder.remoteUrl).toLowerCase();
  }
  return folder.path;
}

/**
 * Resolves the folder that represents a sidebar group. Several registered
 * folders can share one group (a main clone plus linked worktrees of the same
 * repo all have the same remote); the group is labeled by the main checkout,
 * so prefer a folder that is not a linked worktree (`mainRepoPath` is set only
 * on linked worktrees).
 */
export function findGroupFolder<
  F extends {
    path: string;
    remoteUrl: string | null;
    mainRepoPath?: string | null;
  },
>(folders: F[], groupId: string): F | undefined {
  const matches = folders.filter((f) => folderGroupId(f) === groupId);
  return matches.find((f) => !f.mainRepoPath) ?? matches[0];
}

export function groupByRepository<T extends GroupableTask>(
  tasks: T[],
  folderOrder: string[],
  allFolders: { path: string; remoteUrl: string | null; name: string }[] = [],
): TaskGroup<T>[] {
  const groupMap = new Map<string, TaskGroup<T>>();

  for (const task of tasks) {
    const repository = task.repository;
    const isImageBuilder = task.originProduct === "image_builder";
    const groupId = isImageBuilder
      ? CUSTOM_IMAGES_GROUP_ID
      : (repository?.fullPath ?? "other");
    const groupName = isImageBuilder
      ? "Custom images"
      : (repository?.name ?? "Other");

    let group = groupMap.get(groupId);
    if (!group) {
      group = { id: groupId, name: groupName, tasks: [] };
      groupMap.set(groupId, group);
    }

    group.tasks.push(task);
  }

  for (const folder of allFolders) {
    const groupId = folderGroupId(folder);
    if (!groupMap.has(groupId)) {
      groupMap.set(groupId, { id: groupId, name: folder.name, tasks: [] });
    }
  }

  const groups = Array.from(groupMap.values());

  // Disambiguate groups that share a display name (e.g. `posthog/posthog`
  // and `jane/posthog` both rendering as "posthog") by prefixing the
  // organization when it's available.
  const nameCounts = new Map<string, number>();
  for (const group of groups) {
    nameCounts.set(group.name, (nameCounts.get(group.name) ?? 0) + 1);
  }
  for (const group of groups) {
    if ((nameCounts.get(group.name) ?? 0) > 1) {
      const organization = group.tasks[0]?.repository?.organization;
      if (organization) {
        group.name = `${organization}/${group.name}`;
      }
    }
  }

  // Custom-images and "other" always sort last, in that order.
  const pinnedRank = (group: TaskGroup<T>): number => {
    if (group.id === CUSTOM_IMAGES_GROUP_ID) return 1;
    if (group.id === "other") return 2;
    return 0;
  };
  const pinSpecialLast = (a: TaskGroup<T>, b: TaskGroup<T>): number | null => {
    const aRank = pinnedRank(a);
    const bRank = pinnedRank(b);
    if (aRank === 0 && bRank === 0) return null;
    return aRank - bRank;
  };

  if (folderOrder.length === 0) {
    return groups.sort(
      (a, b) => pinSpecialLast(a, b) ?? a.name.localeCompare(b.name),
    );
  }

  return groups.sort((a, b) => {
    const pinned = pinSpecialLast(a, b);
    if (pinned !== null) return pinned;
    const aIndex = folderOrder.indexOf(a.id);
    const bIndex = folderOrder.indexOf(b.id);
    if (aIndex === -1 && bIndex === -1) {
      return a.name.localeCompare(b.name);
    }
    if (aIndex === -1) return 1;
    if (bIndex === -1) return -1;
    return aIndex - bIndex;
  });
}

export interface RelativeDateGroup<T> {
  label: string | null;
  tasks: T[];
}

export function groupTasksByRelativeDate<
  T extends Record<K, number>,
  K extends string,
>(tasks: T[], timestampKey: K): RelativeDateGroup<T>[] {
  const groups: RelativeDateGroup<T>[] = [];
  for (const task of tasks) {
    const label = getRelativeDateGroup(task[timestampKey]);
    const last = groups[groups.length - 1];
    if (last && last.label === label) {
      last.tasks.push(task);
    } else {
      groups.push({ label, tasks: [task] });
    }
  }
  return groups;
}
