import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { useCallback } from "react";

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
      } catch (error) {
        toast.error("Couldn't file task", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [channels, fileTask],
  );
}
