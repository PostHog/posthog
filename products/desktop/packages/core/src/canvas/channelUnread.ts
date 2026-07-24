import type { MentionActivityItem } from "@posthog/core/canvas/mentionActivity";

/**
 * Which channels have activity the viewer hasn't seen — the signal behind the
 * sidebar's bold channel names.
 *
 * "Activity" is currently an @-mention: that's the only cross-channel,
 * all-users feed the client has (the mentions index), and it's what
 * "notification" means elsewhere in the app. The backend exposes no per-channel
 * activity timestamp, so a broader "any new message" signal would mean polling
 * every user's full task list — the app's heaviest poll, deliberately retired.
 * If that timestamp lands, only `latestActivityByChannel` changes shape; the
 * unread comparison and the seen bookkeeping stay as they are.
 *
 * Keyed by backend channel id rather than name, so renaming a channel doesn't
 * silently mark it unread again.
 */

/** Newest activity per channel id. Ignores items with no channel. */
export function latestActivityByChannel(
  items: readonly MentionActivityItem[],
): Map<string, string> {
  const latest = new Map<string, string>();
  for (const item of items) {
    if (!item.channelId) continue;
    const current = latest.get(item.channelId);
    if (!current || item.createdAt > current) {
      latest.set(item.channelId, item.createdAt);
    }
  }
  return latest;
}

/**
 * Channel ids whose newest activity postdates the viewer's last visit. A
 * channel never visited is unread as soon as it has any activity.
 */
export function unreadChannelIds(
  items: readonly MentionActivityItem[],
  lastSeenByChannel: Readonly<Record<string, string>>,
): Set<string> {
  const unread = new Set<string>();
  for (const [channelId, activityAt] of latestActivityByChannel(items)) {
    const seenAt = lastSeenByChannel[channelId];
    if (!seenAt || activityAt > seenAt) unread.add(channelId);
  }
  return unread;
}

/**
 * The newest activity in one channel, for stamping it seen while it's open.
 * Scans for the one channel rather than reusing `latestActivityByChannel`,
 * which would build (and throw away) a map of every other channel to answer.
 */
export function latestActivityForChannel(
  items: readonly MentionActivityItem[],
  channelId: string | undefined,
): string | undefined {
  if (!channelId) return undefined;
  let latest: string | undefined;
  for (const item of items) {
    if (item.channelId !== channelId) continue;
    if (!latest || item.createdAt > latest) latest = item.createdAt;
  }
  return latest;
}
