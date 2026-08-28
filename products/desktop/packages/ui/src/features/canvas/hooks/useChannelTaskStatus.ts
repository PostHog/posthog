import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import type { Task } from "@posthog/shared/domain-types";
import { useChannelTaskData } from "@posthog/ui/features/canvas/hooks/useChannelTaskData";
import { useTaskSessionStarting } from "@posthog/ui/features/sessions/useSession";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";

export interface TaskStatusOptions {
  /**
   * Whether to resolve the PR's state. It is a query per row into the host,
   * where it hits git (and GitHub), so a list that only glances at its rows —
   * the space tree in the sidebar — leaves it off and shows the rest. The
   * PR's existence still comes through `prUrl`, which costs nothing.
   */
  withPrStatus?: boolean;
}

/**
 * The state behind a session's status dot and badges, or `null` for anything
 * with no run to report (a canvas row, a session whose data hasn't landed).
 *
 * Assembled per surface, the same way the Code sidebar's `TaskRow` does it,
 * because that's the only place the inputs exist together: the derived flags
 * come from renderer state (live session, workspace, viewed timestamps) and the
 * PR state from a per-task query, so none of it can be baked into the item list
 * in core. Keeping the composition in a hook rather than in the row leaves the
 * row a component that renders, and gives tests one module to stub.
 */
export function useTaskStatusInput(
  task: Task | undefined,
  options?: TaskStatusOptions,
): TaskStatusInput | null {
  const taskData = useChannelTaskData(task);
  const workspace = useWorkspace(task?.id);
  const isAgentSessionStarting = useTaskSessionStarting(task?.id);
  const { prState, hasDiff, prUrl } = useTaskPrStatus({
    // An empty id is the hook's own "nothing to look up", so this asks for no
    // query rather than one it throws away.
    id: options?.withPrStatus === false ? "" : (task?.id ?? ""),
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
    runMode: taskData.runMode,
    originProduct: taskData.originProduct,
    slackThreadUrl: taskData.slackThreadUrl,
    prState,
    hasDiff,
    isAgentSessionStarting,
    // The url is the early signal: a cloud run writes it the moment it opens the
    // PR, long before (or without ever) resolving the PR's state. A local run
    // has no cloud url, so the one the host cached against the task stands in.
    prUrl: taskData.cloudPrUrl ?? prUrl,
  };
}

/**
 * The same state for a channel row, which holds the whole task on the item so a
 * row doesn't have to look it up again.
 */
export function useChannelTaskStatus(
  item: ChannelItemModel,
  options?: TaskStatusOptions,
): TaskStatusInput | null {
  return useTaskStatusInput(item.task ?? undefined, options);
}
