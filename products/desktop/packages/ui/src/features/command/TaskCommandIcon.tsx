import {
  deriveTaskRunState,
  narrowFullTask,
} from "@posthog/core/sidebar/buildSidebarData";
import type { Task } from "@posthog/shared/domain-types";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useTaskStatusInput } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { TaskIcon } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { TaskDotMark } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";

/**
 * The leading mark on a session row in the command palette.
 *
 * Under the spaces layout it is the space tree's status dot, so a session reads
 * the same wherever it is listed. The legacy layout keeps the older combined
 * icon, which is what the Code sidebar still shows beside it.
 */
export function TaskCommandIcon({ task }: { task: Task }) {
  const spacesLayout = useChannelsLayout();
  return spacesLayout ? (
    <SessionDot task={task} />
  ) : (
    <TaskRunIcon task={task} />
  );
}

/**
 * Dot only, no tooltip: the palette is walked with the keyboard, and a popup
 * that follows the highlight down the list is in the way of reading it.
 *
 * No PR lookup either — that is a host round trip per row, and an empty query
 * lists a screenful of sessions.
 */
function SessionDot({ task }: { task: Task }) {
  const status = useTaskStatusInput(task, { withPrStatus: false });
  return <TaskDotMark dot={taskDot(status ?? {})} />;
}

/**
 * The same shared `TaskIcon` as the sidebar, including cloud run and PR/branch
 * status, deriving its inputs from the raw task and a per-task PR-status query.
 */
function TaskRunIcon({ task }: { task: Task }) {
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
