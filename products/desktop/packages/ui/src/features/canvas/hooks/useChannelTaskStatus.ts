import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useTaskStatusInput } from "@posthog/ui/features/sidebar/useTaskStatusInput";

/**
 * The state behind a channel row's status dot and badges, or `null` for a canvas
 * (which has no run to report).
 */
export function useChannelTaskStatus(
  item: ChannelItemModel,
  options?: { withPrStatus?: boolean },
): TaskStatusInput | null {
  return useTaskStatusInput(item.task ?? undefined, options);
}
