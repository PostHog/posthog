import type { ArchivedTask } from "@posthog/shared";
import { formatRelativeTimeLong } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";

export interface ArchivedTaskDetails
  extends Pick<Task, "id" | "title" | "repository"> {
  created_at: Task["created_at"] | null;
}

export interface ArchivedTaskWithDetails {
  archived: ArchivedTask;
  task: ArchivedTaskDetails | null;
}

export interface ArchivedTaskWithRepo extends ArchivedTaskWithDetails {
  repoName: string;
}

export type ArchiveSortColumn = "created" | "archived";
export type ArchiveSortDirection = "asc" | "desc";

export interface ArchiveSortState {
  column: ArchiveSortColumn;
  direction: ArchiveSortDirection;
}

export interface ArchiveFilterSortInput {
  searchQuery: string;
  repoFilter: string | null;
  sort: ArchiveSortState;
}

export function mergeArchivedWithTasks(
  archivedTasks: ArchivedTask[],
  tasks: ArchivedTaskDetails[],
): ArchivedTaskWithDetails[] {
  const taskMap = new Map(tasks.map((task) => [task.id, task]));
  return archivedTasks.map((archived) => ({
    archived,
    task:
      taskMap.get(archived.taskId) ??
      (archived.title || archived.taskCreatedAt || archived.repository
        ? {
            id: archived.taskId,
            title:
              archived.title ??
              `Unknown task (${archived.branchName ?? archived.worktreeName ?? archived.taskId.slice(0, 8)})`,
            created_at: archived.taskCreatedAt ?? null,
            repository: archived.repository ?? null,
          }
        : null),
  }));
}

export function formatRelativeDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  return formatRelativeTimeLong(isoDate);
}

export function getRepoName(repository: string | null | undefined): string {
  return repository?.split("/").pop() ?? "—";
}

export function withRepoNames(
  items: ArchivedTaskWithDetails[],
): ArchivedTaskWithRepo[] {
  return items.map((item) => ({
    ...item,
    repoName: getRepoName(item.task?.repository),
  }));
}

export function deriveUniqueRepos(items: ArchivedTaskWithRepo[]): string[] {
  const repos = new Set<string>();
  for (const item of items) {
    if (item.repoName !== "—") repos.add(item.repoName);
  }
  return [...repos].sort((a, b) => a.localeCompare(b));
}

function sortTimestamp(
  item: ArchivedTaskWithRepo,
  column: ArchiveSortColumn,
): number {
  if (column === "created") {
    return item.task?.created_at ? new Date(item.task.created_at).getTime() : 0;
  }
  return new Date(item.archived.archivedAt).getTime();
}

export function filterAndSortArchivedTasks(
  items: ArchivedTaskWithRepo[],
  { searchQuery, repoFilter, sort }: ArchiveFilterSortInput,
): ArchivedTaskWithRepo[] {
  let result = items;

  const query = searchQuery.trim().toLowerCase();
  if (query) {
    result = result.filter((item) =>
      [item.task?.title, item.archived.taskId].some((value) =>
        value?.toLowerCase().includes(query),
      ),
    );
  }

  if (repoFilter) {
    result = result.filter((item) => item.repoName === repoFilter);
  }

  const dir = sort.direction === "asc" ? 1 : -1;

  return [...result].sort(
    (a, b) =>
      dir * (sortTimestamp(a, sort.column) - sortTimestamp(b, sort.column)),
  );
}
