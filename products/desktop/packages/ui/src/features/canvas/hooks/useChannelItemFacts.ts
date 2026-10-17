import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { metadataFromValues } from "@posthog/ui/features/sidebar/components/ListItemMetadata";
import {
  activityValue,
  ciValue,
  type ListItemMetadataField,
  type ListItemMetadataValue,
  mergeQueueValue,
} from "@posthog/ui/features/sidebar/listItemAppearance";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { usePrPipelineStatus } from "@posthog/ui/features/sidebar/usePrPipelineStatus";
import type { SidebarPrState } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import type { ReactNode } from "react";

/**
 * What a space list can say about a session, beyond its name. Read off the item
 * rather than resolved here: `buildChannelItems` already did it, and a second
 * resolution is how a row and its section header end up disagreeing about which
 * repository a session belongs to.
 */
type ChannelItemFacts = Partial<
  Record<ListItemMetadataField, ListItemMetadataValue | string>
>;

/**
 * Who made it. A session carries its creator as a user (`authorName` is only
 * ever set for a canvas), so reading the name alone showed no creator on any
 * session row.
 */
export function channelItemAuthor(item: ChannelItemModel): string | null {
  if (item.authorUser) return userDisplayName(item.authorUser);
  return item.authorName;
}

function channelItemFacts(
  item: ChannelItemModel,
  spaceName: string | undefined,
): ChannelItemFacts {
  return {
    space: spaceName,
    repository: item.repository?.label,
    branch: item.branch ?? undefined,
    creator: channelItemAuthor(item) ?? undefined,
    activity: activityValue(item.ts),
  };
}

/**
 * The second row under a session's name, in the order the appearance dialog
 * stored. `pr` is the row's own PR lookup, which the CI and merge queue fields
 * build on.
 */
export function useChannelItemMetadata(
  item: ChannelItemModel,
  spaceName?: string,
  pr?: { prUrl?: string | null; prState?: SidebarPrState },
): ReactNode | undefined {
  const fields = useSidebarStore((state) => state.listItemMetadataFields);
  const pipeline = usePrPipelineStatus({
    prUrl: item.kind === "task" ? pr?.prUrl : null,
    prState: pr?.prState,
  });
  if (fields.length === 0) return undefined;
  return metadataFromValues(
    {
      ...channelItemFacts(item, spaceName),
      ci: ciValue(pipeline?.ci),
      mergeQueue: mergeQueueValue(pipeline?.mergeQueue),
    },
    fields,
  );
}
