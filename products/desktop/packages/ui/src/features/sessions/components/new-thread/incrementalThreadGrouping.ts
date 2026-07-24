import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import {
  buildThreadGroups,
  isGroupableItem,
  type ThreadGrouping,
} from "@posthog/ui/features/sessions/components/new-thread/buildThreadGroups";
import type { CollapseMode } from "@posthog/ui/features/sessions/components/new-thread/conversationThreadConfig";

interface Cache {
  items: ConversationItem[];
  mode: CollapseMode;
  overrides: Record<string, boolean>;
  grouping: ThreadGrouping;
  stablePrefixItemCount: number;
}

/**
 * Caches the grouped prefix of completed turns and only regroups the streamed
 * suffix on each append, instead of re-running buildThreadGroups over the whole
 * transcript every render. Falls back to a full rebuild whenever the input
 * isn't an append of the cached items.
 */
export function createIncrementalThreadGrouper() {
  let cache: Cache | null = null;

  const rebuildAll = (
    items: ConversationItem[],
    mode: CollapseMode,
    overrides: Record<string, boolean>,
  ): ThreadGrouping => {
    const grouping = buildThreadGroups(items, mode, overrides);
    cache = {
      items,
      mode,
      overrides,
      grouping,
      stablePrefixItemCount: findStablePrefixItemCount(items),
    };
    return grouping;
  };

  const update = (
    items: ConversationItem[],
    mode: CollapseMode,
    overrides: Record<string, boolean>,
  ): ThreadGrouping => {
    if (!cache || cache.mode !== mode || cache.overrides !== overrides) {
      return rebuildAll(items, mode, overrides);
    }

    if (cache.items === items) {
      return cache.grouping;
    }

    const stablePrefixItemCount = findStablePrefixItemCount(items);
    const rebuildStart = groupBoundaryAtOrBefore(
      items,
      Math.min(cache.stablePrefixItemCount, stablePrefixItemCount),
    );

    // The cut is only safe if the prefix [0, rebuildStart) is unchanged. The
    // boundary item is enough to verify: stable-prefix items are completed turns
    // frozen by reference in the conversation builder, so a matching boundary
    // means the whole prefix matches.
    if (
      rebuildStart > 0 &&
      cache.items[rebuildStart - 1] !== items[rebuildStart - 1]
    ) {
      return rebuildAll(items, mode, overrides);
    }

    const prefixRowCount = getPrefixRowCount(
      cache.grouping,
      items,
      rebuildStart,
    );
    const suffixGrouping = buildThreadGroups(
      items.slice(rebuildStart),
      mode,
      overrides,
    );

    const rows = [
      ...cache.grouping.rows.slice(0, prefixRowCount),
      ...suffixGrouping.rows,
    ];
    const keepMounted = [
      ...cache.grouping.keepMounted.filter((idx) => idx < prefixRowCount),
      ...suffixGrouping.keepMounted.map((idx) => idx + prefixRowCount),
    ];

    // Build a fresh map rather than mutate cache.grouping's: the previously
    // returned grouping still references that map, and must keep its own row
    // indices. Prefix entries are exactly the ids whose row is below the cut.
    const idToRowIndex = new Map<string, number>();
    for (const [id, idx] of cache.grouping.idToRowIndex) {
      if (idx < prefixRowCount) idToRowIndex.set(id, idx);
    }
    for (const [id, idx] of suffixGrouping.idToRowIndex) {
      idToRowIndex.set(id, idx + prefixRowCount);
    }

    const grouping = { rows, keepMounted, idToRowIndex };
    cache = { items, mode, overrides, grouping, stablePrefixItemCount };
    return grouping;
  };

  return { update };
}

/**
 * Index of the first item belonging to the still-streaming tail: walk back over
 * the trailing run of active (not turn-complete) session updates.
 */
function findStablePrefixItemCount(items: ConversationItem[]): number {
  let count = items.length;
  while (count > 0) {
    const item = items[count - 1];
    if (item.type !== "session_update" || item.turnContext.turnComplete) {
      break;
    }
    count--;
  }
  return count;
}

/**
 * A foldable group is a run of groupable items broken only by item type, never
 * by turn completion, so a single group can straddle the completed/active
 * boundary. Cutting inside it would split one group into two rows that diverge
 * from a full regroup, so back the cut up to the run's start.
 */
function groupBoundaryAtOrBefore(
  items: ConversationItem[],
  index: number,
): number {
  if (
    index === 0 ||
    index >= items.length ||
    !isGroupableItem(items[index - 1]) ||
    !isGroupableItem(items[index])
  ) {
    return index;
  }
  let start = index;
  while (start > 0 && isGroupableItem(items[start - 1])) start--;
  return start;
}

function getPrefixRowCount(
  grouping: ThreadGrouping,
  items: ConversationItem[],
  rebuildStart: number,
): number {
  if (rebuildStart === 0) return 0;

  // The cut lands on a group boundary, so the boundary item starts its own row;
  // its cached row index is the prefix row count. When that item is newly
  // appended (not in the cache), fall back to the last prefix item's row + 1 —
  // a group-boundary cut guarantees it's the last item of its row.
  const boundaryItem = items[rebuildStart];
  const boundaryRowIndex = boundaryItem
    ? grouping.idToRowIndex.get(boundaryItem.id)
    : undefined;
  if (boundaryRowIndex !== undefined) return boundaryRowIndex;

  const lastPrefixItem = items[rebuildStart - 1];
  const lastPrefixRowIndex = lastPrefixItem
    ? grouping.idToRowIndex.get(lastPrefixItem.id)
    : undefined;
  return lastPrefixRowIndex === undefined ? 0 : lastPrefixRowIndex + 1;
}
