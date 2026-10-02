import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useFilingTasksStore } from "@posthog/ui/features/canvas/stores/filingTasksStore";
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
  const startFiling = useFilingTasksStore((state) => state.startFiling);
  const completeFiling = useFilingTasksStore((state) => state.completeFiling);
  const clearFiling = useFilingTasksStore((state) => state.clearFiling);

  return useCallback(
    async (channelId: string, taskId: string) => {
      startFiling(taskId, channelId);
      try {
        await fileTask(channelId, taskId);
        completeFiling(taskId, channelId);
        const channelName = channels.find(
          (channel) => channel.id === channelId,
        )?.name;
        toast.success(channelName ? `Filed to ${channelName}` : "Task filed");
      } catch (error) {
        clearFiling(taskId, channelId);
        toast.error("Couldn't file task", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [channels, clearFiling, completeFiling, fileTask, startFiling],
  );
}
