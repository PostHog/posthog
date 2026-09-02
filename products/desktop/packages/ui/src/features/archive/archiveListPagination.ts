import {
  type ArchivedTaskWithRepo,
  type ArchiveFilterSortInput,
  filterAndSortArchivedTasks,
} from "@posthog/core/archive/archiveListView";

export function getVisibleArchivedTasks(
  items: ArchivedTaskWithRepo[],
  filters: ArchiveFilterSortInput,
  loadedCount: number,
): ArchivedTaskWithRepo[] {
  return filterAndSortArchivedTasks(items, filters).slice(0, loadedCount);
}

export function shouldLoadMoreArchivedTasks(
  lastVirtualRowIndex: number | undefined,
  visibleItemCount: number,
  hasActiveFilter: boolean,
): boolean {
  return (
    !hasActiveFilter &&
    lastVirtualRowIndex !== undefined &&
    lastVirtualRowIndex >= visibleItemCount - 10
  );
}
