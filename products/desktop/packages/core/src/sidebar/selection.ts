import type { SidebarData } from "./sidebarData.types";

export type OrganizeMode = "by-project" | "chronological";

export function computeOrderedVisibleTaskIds(
  sidebarData: Pick<SidebarData, "pinnedTasks" | "flatTasks" | "groupedTasks">,
  organizeMode: OrganizeMode,
  collapsedSections: ReadonlySet<string>,
): string[] {
  const ids: string[] = sidebarData.pinnedTasks.map((task) => task.id);
  if (organizeMode === "by-project") {
    for (const group of sidebarData.groupedTasks) {
      if (collapsedSections.has(group.id)) continue;
      for (const task of group.tasks) ids.push(task.id);
    }
  } else {
    for (const task of sidebarData.flatTasks) ids.push(task.id);
  }
  return ids;
}

export function computeEffectiveBulkIds(
  selectedTaskIds: string[],
  activeTaskId: string | null,
): string[] {
  if (selectedTaskIds.length === 0) return [];
  if (!activeTaskId) return selectedTaskIds;
  if (selectedTaskIds.includes(activeTaskId)) return selectedTaskIds;
  return [activeTaskId, ...selectedTaskIds];
}

export interface RangeSelection {
  selectedTaskIds: string[];
  lastClickedId: string;
}

export function computeRangeSelection(
  anchorId: string | null,
  toId: string,
  orderedIds: string[],
  current: string[],
): RangeSelection {
  if (!anchorId) {
    return { selectedTaskIds: [toId], lastClickedId: toId };
  }
  const anchorIndex = orderedIds.indexOf(anchorId);
  const toIndex = orderedIds.indexOf(toId);
  if (anchorIndex === -1 || toIndex === -1) {
    return { selectedTaskIds: [toId], lastClickedId: toId };
  }
  const start = Math.min(anchorIndex, toIndex);
  const end = Math.max(anchorIndex, toIndex);
  const rangeIds = orderedIds.slice(start, end + 1);
  const merged = Array.from(new Set([...current, ...rangeIds]));
  return { selectedTaskIds: merged, lastClickedId: toId };
}

export function dedupeTaskIds(taskIds: string[]): string[] {
  return Array.from(new Set(taskIds));
}

export function pruneToVisible(
  selectedTaskIds: string[],
  visibleTaskIds: string[],
): string[] {
  const visible = new Set(visibleTaskIds);
  return selectedTaskIds.filter((id) => visible.has(id));
}

export interface PriorTask {
  id: string;
  createdAt: number;
}

export function computePriorTaskIds(
  allVisible: PriorTask[],
  clickedId: string,
): string[] {
  const clicked = allVisible.find((task) => task.id === clickedId);
  if (!clicked) return [];
  const threshold = clicked.createdAt;
  return allVisible
    .filter((task) => task.id !== clickedId && task.createdAt < threshold)
    .map((task) => task.id);
}

export function formatArchiveResult(result: {
  archived: number;
  failed: number;
}): { kind: "success" | "error"; message: string } {
  if (result.failed === 0) {
    return {
      kind: "success",
      message: `${result.archived} ${
        result.archived === 1 ? "task" : "tasks"
      } archived`,
    };
  }
  return {
    kind: "error",
    message: `${result.archived} archived, ${result.failed} failed`,
  };
}
