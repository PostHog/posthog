import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { TurnRow } from "@posthog/ui/features/sessions/components/chat-thread/threadVirtualization";
import { isUserInitiatedConversationItem } from "@posthog/ui/features/sessions/components/isUserInitiatedConversationItem";

type GroupRows = (items: ConversationItem[]) => TurnRow[];

export function createIncrementalChatRowGrouper(groupRows: GroupRows) {
  let cachedItems: ConversationItem[] = [];
  let cachedRows: TurnRow[] = [];

  return {
    update(items: ConversationItem[]): TurnRow[] {
      if (items === cachedItems) return cachedRows;

      let rebuildStart = 0;
      for (let index = items.length - 1; index >= 0; index--) {
        if (isUserInitiatedConversationItem(items[index])) {
          rebuildStart = index;
          break;
        }
      }

      for (let index = 0; index < rebuildStart; index++) {
        if (cachedItems[index] !== items[index]) {
          rebuildStart = 0;
          break;
        }
      }

      let boundaryId = items[rebuildStart]?.id;
      let cachedBoundaryIndex = boundaryId
        ? cachedRows.findIndex((row) => row.id === boundaryId)
        : -1;
      if (
        rebuildStart > 0 &&
        rebuildStart < cachedItems.length &&
        cachedBoundaryIndex < 0
      ) {
        rebuildStart = 0;
        boundaryId = items[0]?.id;
        cachedBoundaryIndex = boundaryId
          ? cachedRows.findIndex((row) => row.id === boundaryId)
          : -1;
      }
      const prefixRowCount =
        rebuildStart === 0
          ? 0
          : cachedBoundaryIndex >= 0
            ? cachedBoundaryIndex
            : cachedRows.length;
      const suffixRows = groupRows(items.slice(rebuildStart));
      cachedItems = items;
      cachedRows = [...cachedRows.slice(0, prefixRowCount), ...suffixRows];
      return cachedRows;
    },
  };
}
