import type { TabsSnapshot } from "@posthog/shared";
import {
  groupForTab,
  type TileGroup,
  tabIdsIn,
} from "@posthog/ui/features/tab-tiling/tileLayout";

/**
 * One pill per split: a group keeps the slot of its first member in the
 * display order (its anchor) and its other members leave the strip. Returns
 * the collapsed order and, per anchor, the group it stands for.
 */
export function collapseSplits(
  displayIds: string[],
  groups: readonly TileGroup[],
): { ids: string[]; groupByAnchor: Map<string, TileGroup> } {
  const groupByAnchor = new Map<string, TileGroup>();
  const hidden = new Set<string>();
  const ids: string[] = [];
  for (const id of displayIds) {
    if (hidden.has(id)) continue;
    const group = groupForTab(groups, id);
    if (group) {
      groupByAnchor.set(id, group);
      for (const member of tabIdsIn(group.root)) {
        if (member !== id) hidden.add(member);
      }
    }
    ids.push(id);
  }
  return { ids, groupByAnchor };
}

/** A window's tab ids in stored order (by position), pin-agnostic. */
export function storedOrderIds(
  snapshot: TabsSnapshot,
  windowId: string,
): string[] {
  return snapshot.tabs
    .filter((t) => t.windowId === windowId)
    .sort((a, b) => a.position - b.position)
    .map((t) => t.id);
}

/**
 * Stable pinned-first partition of a stored id order: pinned tabs move to the
 * front, each group keeping its stored relative order. This is the strip's
 * display order — a pure view concern layered over the (pin-agnostic) stored
 * positions.
 */
export function partitionPinnedFirst(
  storedIds: string[],
  pinnedTabIds: string[],
): string[] {
  const pinned = new Set(pinnedTabIds);
  const front: string[] = [];
  const back: string[] = [];
  for (const id of storedIds) (pinned.has(id) ? front : back).push(id);
  return [...front, ...back];
}

/**
 * The strip's displayed tab order for a window: stored order with the
 * pinned-first partition applied. Shared by the strip's render and the drag
 * handler so drops always commit against what was on screen.
 */
export function displayedTabIds(
  snapshot: TabsSnapshot,
  windowId: string,
  pinnedTabIds: string[],
): string[] {
  return partitionPinnedFirst(storedOrderIds(snapshot, windowId), pinnedTabIds);
}

/**
 * Reorder within one pin group only: move `srcId` to `tgtId`'s slot among the
 * tabs sharing its pin state, leaving every tab in the *other* group at its
 * exact stored slot. This keeps a drag of an unpinned tab from ever disturbing
 * a pinned tab's stored position (and vice versa), so the pinned-first display
 * partition is never baked into the canonical stored order.
 */
export function reorderWithinGroup(
  storedIds: string[],
  pinnedTabIds: string[],
  srcId: string,
  tgtId: string,
): string[] {
  const pinned = new Set(pinnedTabIds);
  const srcPinned = pinned.has(srcId);
  if (srcPinned !== pinned.has(tgtId)) return storedIds;
  const group = storedIds.filter((id) => pinned.has(id) === srcPinned);
  const from = group.indexOf(srcId);
  const to = group.indexOf(tgtId);
  if (from === -1 || to === -1 || from === to) return storedIds;
  const [moved] = group.splice(from, 1);
  group.splice(to, 0, moved);
  // Refill the group's slots in the stored sequence with the reordered group;
  // the other group's tabs stay exactly where they were.
  let gi = 0;
  return storedIds.map((id) =>
    pinned.has(id) === srcPinned ? group[gi++] : id,
  );
}

/**
 * Stored order that puts `tabId` just before the first tab still in the
 * unpinned block (i.e. front of the unpinned block once it is unpinned),
 * leaving every other tab's relative order intact. The reorder primitive
 * behind "unpinning re-homes the tab to the front of the unpinned block".
 */
export function frontOfUnpinnedOrder(
  snapshot: TabsSnapshot,
  windowId: string,
  tabId: string,
  pinnedTabIds: string[],
): string[] {
  const remainingPinned = new Set(pinnedTabIds.filter((id) => id !== tabId));
  const stored = storedOrderIds(snapshot, windowId).filter(
    (id) => id !== tabId,
  );
  const firstUnpinned = stored.findIndex((id) => !remainingPinned.has(id));
  const at = firstUnpinned === -1 ? stored.length : firstUnpinned;
  return [...stored.slice(0, at), tabId, ...stored.slice(at)];
}
