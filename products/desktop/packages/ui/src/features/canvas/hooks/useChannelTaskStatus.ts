import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { useChannelTaskData } from "@posthog/ui/features/canvas/hooks/useChannelTaskData";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";

/**
 * The state behind a channel row's status dot and badges, or `null` for a canvas
 * (which has no run to report).
 *
 * Assembled per row, the same way the Code sidebar's `TaskRow` does it, because
 * that's the only place the inputs exist together: the derived flags come from
 * renderer state (live session, workspace, viewed timestamps) and the PR state
 * from a per-task query, so none of it can be baked into the item list in core.
 * Keeping the composition in a hook rather than in the row leaves the row a
 * component that renders, and gives tests one module to stub.
 */
export function useChannelTaskStatus(
  item: ChannelItemModel,
): TaskStatusInput | null {
  const task = item.task ?? undefined;
  const taskData = useChannelTaskData(task);
  const workspace = useWorkspace(task?.id);
  const { prState, hasDiff } = useTaskPrStatus({
    id: task?.id ?? "",
    cloudPrUrl: taskData?.cloudPrUrl ?? null,
    taskRunEnvironment: taskData?.taskRunEnvironment ?? null,
  });

  if (!taskData) return null;
  return {
    workspaceMode:
      workspace?.mode ??
      (taskData.taskRunEnvironment === "cloud" ? "cloud" : undefined),
    isGenerating: taskData.isGenerating,
    isUnread: taskData.isUnread,
    isPinned: taskData.isPinned,
    isSuspended: taskData.isSuspended,
    needsPermission: taskData.needsPermission,
    taskRunStatus: taskData.taskRunStatus,
    originProduct: taskData.originProduct,
    slackThreadUrl: taskData.slackThreadUrl,
    prState,
    hasDiff,
    // The url is the early signal: a cloud run writes it the moment it opens the
    // PR, long before (or without ever) resolving the PR's state.
    prUrl: taskData.cloudPrUrl,
  };
}
