import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ToolGroupItem } from "@posthog/ui/features/sessions/components/chat-thread/ToolGroup";

/**
 * Plain-text transcript of a turn's agent prose, in order.
 *
 * User prompts, tool calls, thoughts and status rows are left out — this is for pasting an answer
 * somewhere else, not for reproducing the run. Returns null when the rows carry no prose.
 */
export function buildTurnCopyText(
  items: Array<ConversationItem | ToolGroupItem>,
): string | null {
  const parts: string[] = [];

  for (const item of items) {
    if (item.type !== "session_update") continue;
    const update = item.update;
    if (update.sessionUpdate !== "agent_message_chunk") continue;
    if (update.content.type !== "text") continue;
    const text = update.content.text.trim();
    if (text) parts.push(text);
  }

  if (parts.length === 0) return null;
  return parts.join("\n\n");
}

interface TurnCopyTextCacheEntry {
  itemCount: number;
  lastItem: unknown;
  text: string | null;
}

const turnCopyTextCache = new WeakMap<object, TurnCopyTextCacheEntry>();

/**
 * {@link buildTurnCopyText} with per-turn memoization. The thread re-derives
 * its rows on every streamed chunk and rebuilds each turn's container array,
 * so an uncached call re-serializes the prose of every completed turn several
 * times a second for the length of a run. The cache keys on the turn's first
 * item, which is identity-stable once a turn completes; the item count and
 * last-item guards invalidate the entry when a turn still gains items. Keys
 * are the item objects themselves, so entries release with the transcript.
 */
export function buildTurnCopyTextCached(
  items: Array<ConversationItem | ToolGroupItem>,
): string | null {
  const first = items[0];
  if (!first) return null;
  const last = items[items.length - 1];
  const hit = turnCopyTextCache.get(first);
  if (hit && hit.itemCount === items.length && hit.lastItem === last) {
    return hit.text;
  }
  const text = buildTurnCopyText(items);
  turnCopyTextCache.set(first, {
    itemCount: items.length,
    lastItem: last,
    text,
  });
  return text;
}
