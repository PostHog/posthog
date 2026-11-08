import { stripTrailingAttachmentSummary } from "@posthog/core/editor/cloud-prompt";
import {
  hasInjectedBlocks,
  stripInjectedBlocks,
} from "@posthog/core/editor/injectedBlocks";
import type { ConversationItem } from "./buildConversationItems";

interface MergeConversationItemsArgs {
  conversationItems: ConversationItem[];
  optimisticItems: ConversationItem[];
  isCloud: boolean;
  tailAnchors?: Map<string, string | null>;
}

type UserMessageItem = Extract<ConversationItem, { type: "user_message" }>;

function strippedUserContent(content: string): string {
  return stripTrailingAttachmentSummary(stripInjectedBlocks(content));
}

function reconcileInitialPromptEcho(
  items: ConversationItem[],
): ConversationItem[] {
  let initial: UserMessageItem | undefined;
  for (let index = 0; index < items.length; index++) {
    const item = items[index];
    if (
      item.type === "session_update" &&
      item.update.sessionUpdate === "progress_group"
    ) {
      continue;
    }
    if (item.type !== "user_message") return items;
    if (!initial) {
      if (hasInjectedBlocks(item.content)) return items;
      initial = item;
      continue;
    }
    if (
      !hasInjectedBlocks(item.content) ||
      strippedUserContent(initial.content) !== strippedUserContent(item.content)
    ) {
      return items;
    }
    // The stored startup transcript can contain both the bare request and its
    // context-bearing echo even after the in-memory optimistic row is gone.
    return items
      .filter((_, itemIndex) => itemIndex !== index)
      .map((entry) =>
        entry === initial ? { ...item, id: initial.id } : entry,
      );
  }
  return items;
}

// Cloud's initial optimistic is pinned to the top so the user's prompt stays
// visible above setup progress. Follow-up optimistics render at the tail, but
// before trailing progress cards, to match where the streamed `session/prompt`
// will appear. With `tailAnchors`, each follow-up stays after the row that was
// last when it was first rendered. A cloud steer that the run declines gets its
// echo only when the turn ends, so without the anchor the agent output of the
// whole turn renders above the message.
//
// Local sessions keep optimistic at the chronological end — they rely on
// `replaceOptimisticWithEvent` to swap optimistic↔real in place.
export function mergeConversationItems({
  conversationItems,
  optimisticItems,
  isCloud,
  tailAnchors,
}: MergeConversationItemsArgs): ConversationItem[] {
  if (isCloud) {
    conversationItems = reconcileInitialPromptEcho(conversationItems);
  }
  if (optimisticItems.length === 0) {
    return conversationItems;
  }

  if (!isCloud) {
    return [...conversationItems, ...optimisticItems];
  }

  const pinnedOptimisticItems = optimisticItems.filter(
    (item) => item.type !== "user_message" || item.pinToTop !== false,
  );
  const tailOptimisticItems = optimisticItems.filter(
    (item) => item.type === "user_message" && item.pinToTop === false,
  );
  const unconsumedPinnedKeyCounts = new Map<string, number>();
  for (const item of pinnedOptimisticItems) {
    if (item.type !== "user_message") continue;
    const key = strippedUserContent(item.content);
    unconsumedPinnedKeyCounts.set(
      key,
      (unconsumedPinnedKeyCounts.get(key) ?? 0) + 1,
    );
  }

  // When the echoed prompt matches a pinned optimistic placeholder, drop the
  // echo but remember it. The server copy supplies the authoritative timestamp
  // as well as context and attachments, while the optimistic id keeps the row stable.
  const echoedItemByKey = new Map<string, UserMessageItem>();
  const consumedPlainEchoByKey = new Set<string>();
  const dedupedConversation =
    unconsumedPinnedKeyCounts.size === 0
      ? conversationItems
      : conversationItems.filter((item) => {
          if (item.type !== "user_message") return true;
          const key = strippedUserContent(item.content);
          const remaining = unconsumedPinnedKeyCounts.get(key) ?? 0;
          if (remaining > 0) {
            unconsumedPinnedKeyCounts.set(key, remaining - 1);
            echoedItemByKey.set(key, item);
            if (!hasInjectedBlocks(item.content))
              consumedPlainEchoByKey.add(key);
            return false;
          }

          if (
            consumedPlainEchoByKey.has(key) &&
            hasInjectedBlocks(item.content)
          ) {
            echoedItemByKey.set(key, item);
            consumedPlainEchoByKey.delete(key);
            return false;
          }
          return true;
        });

  const resolvedPinnedItems =
    echoedItemByKey.size === 0
      ? pinnedOptimisticItems
      : pinnedOptimisticItems.map((item) => {
          if (item.type !== "user_message") return item;
          const echoed = echoedItemByKey.get(strippedUserContent(item.content));
          if (!echoed) return item;
          const resolvedItem = {
            ...item,
            timestamp: echoed.timestamp,
            pinToTop: undefined,
          };
          if (echoed.content === item.content && !echoed.attachments?.length) {
            return resolvedItem;
          }
          return {
            ...resolvedItem,
            content: echoed.content,
            ...(echoed.attachments?.length
              ? { attachments: echoed.attachments }
              : {}),
          };
        });

  let tailInsertionIndex = dedupedConversation.length;
  while (tailInsertionIndex > 0) {
    const item = dedupedConversation[tailInsertionIndex - 1];
    if (
      item.type === "session_update" &&
      item.update.sessionUpdate === "progress_group"
    ) {
      tailInsertionIndex--;
    } else {
      break;
    }
  }

  if (!tailAnchors || tailOptimisticItems.length === 0) {
    return [
      ...resolvedPinnedItems,
      ...dedupedConversation.slice(0, tailInsertionIndex),
      ...tailOptimisticItems,
      ...dedupedConversation.slice(tailInsertionIndex),
    ];
  }

  const tailIds = new Set(tailOptimisticItems.map((item) => item.id));
  for (const id of tailAnchors.keys()) {
    if (!tailIds.has(id)) tailAnchors.delete(id);
  }
  const indexById = new Map(
    dedupedConversation.map((item, index) => [item.id, index]),
  );
  const tailItemsByIndex = new Map<number, ConversationItem[]>();
  for (const item of tailOptimisticItems) {
    if (!tailAnchors.has(item.id)) {
      tailAnchors.set(
        item.id,
        dedupedConversation[tailInsertionIndex - 1]?.id ?? null,
      );
    }
    const anchorId = tailAnchors.get(item.id);
    const anchorIndex = anchorId == null ? -1 : indexById.get(anchorId);
    const insertionIndex =
      anchorIndex === undefined ? tailInsertionIndex : anchorIndex + 1;
    const itemsAtIndex = tailItemsByIndex.get(insertionIndex) ?? [];
    itemsAtIndex.push(item);
    tailItemsByIndex.set(insertionIndex, itemsAtIndex);
  }

  const merged = [...resolvedPinnedItems];
  for (let index = 0; index <= dedupedConversation.length; index++) {
    merged.push(...(tailItemsByIndex.get(index) ?? []));
    if (index < dedupedConversation.length) {
      merged.push(dedupedConversation[index]);
    }
  }
  return merged;
}
