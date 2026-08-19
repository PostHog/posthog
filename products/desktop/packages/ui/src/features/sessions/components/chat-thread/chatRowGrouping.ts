import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { TurnRow } from "@posthog/ui/features/sessions/components/chat-thread/threadVirtualization";
import { isUserInitiatedConversationItem } from "@posthog/ui/features/sessions/components/isUserInitiatedConversationItem";

type GroupRows = (items: ConversationItem[]) => TurnRow[];

export function createIncrementalChatRowGrouper(groupRows: GroupRows) {
  let cachedItems: ConversationItem[] = [];
  let cachedRows: TurnRow[] = [];
  const cachedRowIndexes = new Map<string, number>();

  const rebuildAll = (items: ConversationItem[]): TurnRow[] => {
    cachedItems = items;
    cachedRows = groupRows(items);
    cachedRowIndexes.clear();
    cachedRows.forEach((row, index) => {
      cachedRowIndexes.set(row.id, index);
    });
    return cachedRows;
  };

  return {
    update(items: ConversationItem[], stablePrefixItemCount = 0): TurnRow[] {
      if (items === cachedItems) return cachedRows;

      let rebuildStart = 0;
      for (
        let index = Math.min(stablePrefixItemCount, items.length - 1);
        index >= 0;
        index--
      ) {
        if (isUserInitiatedConversationItem(items[index])) {
          rebuildStart = index;
          break;
        }
      }

      const boundaryId = items[rebuildStart]?.id;
      const cachedBoundaryIndex = boundaryId
        ? (cachedRowIndexes.get(boundaryId) ?? -1)
        : -1;
      if (
        rebuildStart > 0 &&
        rebuildStart < cachedItems.length &&
        cachedBoundaryIndex < 0
      ) {
        return rebuildAll(items);
      }
      const prefixRowCount =
        rebuildStart === 0
          ? 0
          : cachedBoundaryIndex >= 0
            ? cachedBoundaryIndex
            : cachedRows.length;
      const suffixRows = groupRows(items.slice(rebuildStart));
      for (let index = prefixRowCount; index < cachedRows.length; index++) {
        cachedRowIndexes.delete(cachedRows[index].id);
      }
      suffixRows.forEach((row, index) => {
        cachedRowIndexes.set(row.id, prefixRowCount + index);
      });
      cachedItems = items;
      cachedRows = [...cachedRows.slice(0, prefixRowCount), ...suffixRows];
      return cachedRows;
    },
  };
}
