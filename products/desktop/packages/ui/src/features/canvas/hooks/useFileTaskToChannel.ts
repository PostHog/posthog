import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback } from "react";

function trackFiling(channelId: string, taskId: string, success: boolean) {
  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
    action_type: "file_task",
    surface: "task_context_menu",
    channel_id: channelId,
    task_id: taskId,
    success,
  });
}

/**
 * Files a task to a space and reports the outcome, naming the space in the
 * success toast. Extracted so the row menu and the native context menu file
 * tasks the same way — filing is a mutation plus the two toasts that make it
 * legible, and duplicating that is how the two paths drift.
 */
export function useFileTaskToChannel(): (
  channelId: string,
  taskId: string,
  taskTitle: string,
) => Promise<void> {
  const { fileTask } = useChannelTaskMutations();
  const { channels } = useChannels();

  return useCallback(
    async (channelId: string, taskId: string) => {
      try {
        await fileTask(channelId, taskId);
        const channelName = channels.find(
          (channel) => channel.id === channelId,
        )?.name;
        toast.success(channelName ? `Filed to ${channelName}` : "Task filed");
        trackFiling(channelId, taskId, true);
      } catch (error) {
        trackFiling(channelId, taskId, false);
        toast.error("Couldn't file task", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [channels, fileTask],
  );
}
