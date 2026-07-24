import type { TaskMention, UserBasic } from "@posthog/shared/domain-types";

/**
 * The Activity feed — thread messages that @-mention the current user — as
 * served by the backend mentions index (`getTaskMentions`). Mentions are
 * extracted server-side at write time, so the client only maps DTOs to items.
 */

export interface MentionActivityItem {
  messageId: string;
  taskId: string;
  taskTitle: string;
  /** Backend channel (tasks product Channel UUID); null for channel-less tasks. */
  channelId: string | null;
  /** Backend channel name, for the "#channel" label. */
  channelName: string | null;
  author: UserBasic | null;
  content: string;
  createdAt: string;
}

/** Map mention DTOs (already newest-first from the backend) to feed items. */
export function toMentionActivityItems(
  mentions: readonly TaskMention[],
): MentionActivityItem[] {
  return mentions.map((mention) => ({
    messageId: mention.message_id,
    taskId: mention.task_id,
    taskTitle: mention.task_title || "Untitled task",
    channelId: mention.channel_id ?? null,
    channelName: mention.channel_name ?? null,
    author: mention.author ?? null,
    content: mention.content,
    createdAt: mention.created_at,
  }));
}

/** How many items arrived after the viewer last opened the Activity page. */
export function countUnseenActivity(
  items: readonly MentionActivityItem[],
  lastSeenAt: string | null,
): number {
  if (!lastSeenAt) return items.length;
  return items.filter((item) => item.createdAt > lastSeenAt).length;
}

// Bounds the cache so a long-running session's accumulated feed can't grow
// without limit.
const MAX_CACHED_MENTIONS = 300;

/**
 * Fold a page of freshly-fetched mentions into the previously cached set —
 * dedupe by message, keep newest first. Lets repolls fetch only what's new
 * (via `since`) instead of re-fetching the whole top page every time.
 */
export function mergeTaskMentions(
  previous: readonly TaskMention[],
  incoming: readonly TaskMention[],
): TaskMention[] {
  if (incoming.length === 0) return [...previous];
  const byMessageId = new Map(
    previous.map((mention) => [mention.message_id, mention]),
  );
  for (const mention of incoming) byMessageId.set(mention.message_id, mention);
  return Array.from(byMessageId.values())
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
    .slice(0, MAX_CACHED_MENTIONS);
}
