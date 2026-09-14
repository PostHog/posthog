import {
  deriveTaskRunState,
  narrowFullTask,
} from "@posthog/core/sidebar/buildSidebarData";
import type { Task } from "@posthog/shared/domain-types";
import { TaskIcon } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { SlackMark } from "@posthog/ui/primitives/SlackMark";

/**
 * The leading mark on a session row in the command palette.
 *
 * The palette answers one query with tasks, spaces, canvases, pull requests and
 * files in the same list, so each row keeps the mark its own surface uses: the
 * sidebar's run and PR status icon, and Slack's own mark for a session a person
 * started from Slack.
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
  if (task.origin_product === "slack") return <SlackMark size={12} />;
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
