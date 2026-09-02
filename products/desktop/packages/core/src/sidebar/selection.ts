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

/** Same ids in the same order, so a rewrite of an unchanged selection is a no-op. */
export function sameTaskIds(
  a: readonly string[],
  b: readonly string[],
): boolean {
  return a.length === b.length && a.every((id, i) => id === b[i]);
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
  lastActivityAt: number;
}

/** Ids that went quiet before the clicked one, i.e. what "archive prior" covers. */
export function computePriorTaskIds(
  allVisible: PriorTask[],
  clickedId: string,
): string[] {
  const clicked = allVisible.find((task) => task.id === clickedId);
  if (!clicked) return [];
  const threshold = clicked.lastActivityAt;
  return allVisible
    .filter((task) => task.id !== clickedId && task.lastActivityAt < threshold)
    .map((task) => task.id);
}

/**
 * Which way a bulk pin should go. Pinning wins a mixed selection so the result
 * is predictable — flipping each session independently would leave the group
 * split across the pinned and unpinned sections.
 */
export function computeBulkPinDirection(
  selectedTaskIds: string[],
  pinnedTaskIds: ReadonlySet<string>,
): "pin" | "unpin" {
  if (selectedTaskIds.length === 0) return "pin";
  return selectedTaskIds.every((id) => pinnedTaskIds.has(id)) ? "unpin" : "pin";
}

export function sessionsLabel(count: number): string {
  return `${count} ${count === 1 ? "session" : "sessions"}`;
}

/**
 * What archiving a selection costs beyond the archive itself. Shared so the
 * action bar's dialog and the native right-click confirm can't drift.
 */
export function formatBulkArchiveWarning(counts: {
  running: number;
  stopsCloudSandbox: boolean;
}): string {
  const parts = ["You can unarchive them later."];
  if (counts.running > 0) {
    parts.push(
      `${counts.running} of them ${counts.running === 1 ? "is" : "are"} still running and will be stopped.`,
    );
  }
  if (counts.stopsCloudSandbox) {
    parts.push("Any cloud sandbox in the selection shuts down too.");
  }
  return parts.join(" ");
}

/** Past-tense verb naming what a bulk action did, for its result toast. */
export type BulkResultKind =
  | "archived"
  | "pinned"
  | "unpinned"
  | "filed"
  | "added to Command Center";

export interface BulkResult {
  succeeded: number;
  failed: number;
}

export function formatBulkResult(
  kind: BulkResultKind,
  result: BulkResult,
): { kind: "success" | "error"; message: string } {
  if (result.failed === 0) {
    return {
      kind: "success",
      message: `${sessionsLabel(result.succeeded)} ${kind}`,
    };
  }
  return {
    kind: "error",
    message: `${result.succeeded} ${kind}, ${result.failed} failed`,
  };
}

export function formatArchiveResult(result: {
  archived: number;
  failed: number;
}): { kind: "success" | "error"; message: string } {
  return formatBulkResult("archived", {
    succeeded: result.archived,
    failed: result.failed,
  });
}
