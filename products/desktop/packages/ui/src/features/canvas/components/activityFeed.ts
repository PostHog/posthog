import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { normalizeChannelName } from "@posthog/ui/features/canvas/hooks/useTaskChannels";

interface NamedChannel {
  id: string;
  name: string;
}

export function createChannelIdByName(
  channels: NamedChannel[],
): Map<string, string> {
  return new Map(
    channels.map((channel) => [normalizeChannelName(channel.name), channel.id]),
  );
}

export function channelIdForName(
  channelIdByName: Map<string, string>,
  channelName: string | null,
): string | null {
  return channelName
    ? (channelIdByName.get(normalizeChannelName(channelName)) ?? null)
    : null;
}

export function getUnreadActivityItems(
  items: TaskActivityItem[],
): TaskActivityItem[] {
  return items.filter((item) => item.isUnread);
}

export function activityReadPayload(items: TaskActivityItem[]) {
  return items.map((item) => ({
    task_id: item.taskId,
    seen_before: item.activityAt,
  }));
}

export function markLoadedReadLabel(
  loadedUnreadCount: number,
  unreadCount: number,
): string {
  return loadedUnreadCount === unreadCount
    ? "Mark all as read"
    : "Mark visible as read";
}
