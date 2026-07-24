import { stripTrailingAttachmentSummary } from "@posthog/core/editor/cloud-prompt";
import type { ConversationItem } from "./buildConversationItems";
import { extractChannelContext } from "./session-update/channelContext";
import { extractCustomInstructions } from "./session-update/customInstructions";

interface MergeConversationItemsArgs {
  conversationItems: ConversationItem[];
  optimisticItems: ConversationItem[];
  isCloud: boolean;
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

// Cloud's initial optimistic is pinned to the top so the user's prompt stays
// visible above setup progress. Follow-up optimistics render at the tail until
// the streamed `session/prompt` arrives and replaces them.
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
  // echo but remember it: it may carry the channel CONTEXT.md block and the
  // attachment chips the placeholder lacks, so we surface the richer copy on
  // the pinned bubble below.
  const echoedItemByKey = new Map<string, UserMessageItem>();
  const dedupedConversation =
    unconsumedPinnedKeyCounts.size === 0
      ? conversationItems
      : conversationItems.filter((item) => {
          if (item.type !== "user_message") return true;
          const key = strippedUserContent(item.content);
          const remaining = unconsumedPinnedKeyCounts.get(key) ?? 0;
          if (remaining === 0) return true;
          unconsumedPinnedKeyCounts.set(key, remaining - 1);
          if (!echoedItemByKey.has(key)) {
            echoedItemByKey.set(key, item);
          }
          return false;
        });

  const resolvedPinnedItems =
    echoedItemByKey.size === 0
      ? pinnedOptimisticItems
      : pinnedOptimisticItems.map((item) => {
          if (item.type !== "user_message") return item;
          const echoed = echoedItemByKey.get(strippedUserContent(item.content));
          if (
            !echoed ||
            (echoed.content === item.content && !echoed.attachments?.length)
          ) {
            return item;
          }
          return {
            ...item,
            content: echoed.content,
            ...(echoed.attachments?.length
              ? { attachments: echoed.attachments }
              : {}),
          };
        });

  return [
    ...resolvedPinnedItems,
    ...dedupedConversation,
    ...tailOptimisticItems,
  ];
}
