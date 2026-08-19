import { stripTrailingAttachmentSummary } from "@posthog/core/editor/cloud-prompt";
import type { ConversationItem } from "./buildConversationItems";
import {
  extractChannelContext,
  hasChannelContext,
} from "./session-update/channelContext";
import {
  extractCustomInstructions,
  hasCustomInstructions,
} from "./session-update/customInstructions";

interface MergeConversationItemsArgs {
  conversationItems: ConversationItem[];
  optimisticItems: ConversationItem[];
  isCloud: boolean;
}

interface IncrementalMergeConversationItemsArgs
  extends MergeConversationItemsArgs {
  stablePrefixItemCount: number;
}

interface IncrementalMergeResult {
  items: ConversationItem[];
  stablePrefixItemCount: number;
}

type UserMessageItem = Extract<ConversationItem, { type: "user_message" }>;

// The pinned optimistic bubble is seeded from the bare task description, but the
// echoed `session/prompt` that streams back from the sandbox may additionally
// carry the channel's CONTEXT.md and/or the user's personalization, folded into
// the prompt at task creation (see buildChannelContextText /
// buildCustomInstructionsText in @posthog/core). The description side instead
// appends an `Attached files: <names>` summary line that the echo carries as
// resource_link blocks, not text (see buildCloudTaskDescription). Dedupe and
// upgrade compare on the text with all three stripped so the echo still matches
// its placeholder.
function strippedUserContent(content: string): string {
  const withoutChannel = extractChannelContext(content)?.stripped ?? content;
  const withoutInstructions =
    extractCustomInstructions(withoutChannel)?.stripped ?? withoutChannel;
  return stripTrailingAttachmentSummary(withoutInstructions);
}

function hasShadowContext(content: string): boolean {
  return hasChannelContext(content) || hasCustomInstructions(content);
}

// Cloud's initial optimistic is pinned to the top so the user's prompt stays
// visible above setup progress. Follow-up optimistics render at the tail, but
// before trailing progress cards, to match where the streamed `session/prompt`
// will appear.
//
// Local sessions keep optimistic at the chronological end — they rely on
// `replaceOptimisticWithEvent` to swap optimistic↔real in place.
export function mergeConversationItems({
  conversationItems,
  optimisticItems,
  isCloud,
}: MergeConversationItemsArgs): ConversationItem[] {
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
            if (!hasShadowContext(item.content))
              consumedPlainEchoByKey.add(key);
            return false;
          }

          if (
            consumedPlainEchoByKey.has(key) &&
            hasShadowContext(item.content)
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

  return [
    ...resolvedPinnedItems,
    ...dedupedConversation.slice(0, tailInsertionIndex),
    ...tailOptimisticItems,
    ...dedupedConversation.slice(tailInsertionIndex),
  ];
}

function sameUserMessage(
  left: ConversationItem,
  right: ConversationItem,
): boolean {
  return (
    left.type === "user_message" &&
    right.type === "user_message" &&
    left.id === right.id &&
    left.content === right.content &&
    left.timestamp === right.timestamp &&
    left.attachments === right.attachments &&
    left.pinToTop === right.pinToTop
  );
}

export function createIncrementalConversationMerger() {
  let previousItems: ConversationItem[] = [];

  return {
    update({
      conversationItems,
      optimisticItems,
      isCloud,
      stablePrefixItemCount,
    }: IncrementalMergeConversationItemsArgs): IncrementalMergeResult {
      let items = mergeConversationItems({
        conversationItems,
        optimisticItems,
        isCloud,
      });
      if (stablePrefixItemCount === 0 || previousItems.length === 0) {
        previousItems = items;
        return { items, stablePrefixItemCount: 0 };
      }

      const stableItems = mergeConversationItems({
        conversationItems: conversationItems.slice(0, stablePrefixItemCount),
        optimisticItems,
        isCloud,
      });
      let mergedStablePrefixItemCount = 0;
      while (
        mergedStablePrefixItemCount < items.length &&
        mergedStablePrefixItemCount < stableItems.length &&
        mergedStablePrefixItemCount < previousItems.length
      ) {
        const item = items[mergedStablePrefixItemCount];
        const stableItem = stableItems[mergedStablePrefixItemCount];
        const previousItem = previousItems[mergedStablePrefixItemCount];
        if (item !== stableItem && !sameUserMessage(item, stableItem)) {
          break;
        }
        if (item !== previousItem && !sameUserMessage(item, previousItem)) {
          break;
        }
        if (item !== previousItem) {
          if (items === conversationItems) {
            items = items.slice();
          }
          items[mergedStablePrefixItemCount] = previousItem;
        }
        mergedStablePrefixItemCount++;
      }

      previousItems = items;
      return { items, stablePrefixItemCount: mergedStablePrefixItemCount };
    },
  };
}
