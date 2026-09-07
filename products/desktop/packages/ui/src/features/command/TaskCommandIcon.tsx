import {
  deriveTaskRunState,
  narrowFullTask,
} from "@posthog/core/sidebar/buildSidebarData";
import type { Task } from "@posthog/shared/domain-types";
import { TaskIcon } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";

/**
 * Task icon for the command palette. Renders the same shared `TaskIcon` as
 * the sidebar, including cloud run and PR/branch status, while deriving its
 * inputs from the raw task and a per-task PR-status query.
 */
export function TaskCommandIcon({ task }: { task: Task }) {
  const { prState, hasDiff } = useTaskPrStatus({
    id: task.id,
    cloudPrUrl: null,
    taskRunEnvironment: task.latest_run?.environment,
  });
  const sidebarTask = narrowFullTask(task);
  const runState = deriveTaskRunState(sidebarTask, undefined);
  const stateSlackThreadUrl = (
    task.latest_run?.state as { slack_thread_url?: unknown } | undefined
  )?.slack_thread_url;
  const slackThreadUrl =
    typeof stateSlackThreadUrl === "string" ? stateSlackThreadUrl : undefined;
  return (
    <TaskIcon
      workspaceMode={runState.taskRunEnvironment}
      isGenerating={runState.isGenerating}
      taskRunStatus={runState.taskRunStatus}
      runMode={sidebarTask.latest_run?.mode ?? undefined}
      originProduct={task.origin_product}
      slackThreadUrl={slackThreadUrl}
      prState={prState}
      hasDiff={hasDiff}
    />
  );
}
