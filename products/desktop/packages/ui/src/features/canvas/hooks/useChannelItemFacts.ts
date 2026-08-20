import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  activityValue,
  type ListItemMetadataField,
  type ListItemMetadataSegment,
  type ListItemMetadataValue,
  listItemMetadataSegments,
} from "@posthog/ui/features/sidebar/listItemAppearance";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";

/**
 * What a space list can say about a session, beyond its name. Read off the item
 * rather than resolved here: `buildChannelItems` already did it, and a second
 * resolution is how a row and its section header end up disagreeing about which
 * repository a session belongs to.
 */
export type ChannelItemFacts = Partial<
  Record<ListItemMetadataField, ListItemMetadataValue>
>;

export function channelItemFacts(item: ChannelItemModel): ChannelItemFacts {
  return {
    repository: item.repository?.label,
    branch: item.branch ?? undefined,
    creator: item.authorName ?? undefined,
    activity: activityValue(item.ts),
  };
}

/**
 * The second row under a session's name, in the order the appearance dialog
 * stored.
 */
export function useChannelItemMetadata(
  item: ChannelItemModel,
): ListItemMetadataSegment[] {
  const fields = useSidebarStore((state) => state.listItemMetadataFields);
  if (fields.length === 0) return [];
  return listItemMetadataSegments(channelItemFacts(item), fields);
}
