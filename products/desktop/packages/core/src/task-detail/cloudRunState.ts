import {
  type ChangedFile,
  isTerminalStatus,
  type Task,
  type TaskRunStatus,
} from "@posthog/shared/domain-types";

export interface CloudRunSessionLike {
  taskRunId?: string | null;
  cloudBranch?: string | null;
  cloudStatus?: TaskRunStatus | null;
}

/**
 * Effective run status for the UI: a terminal task status always wins;
 * otherwise the session's live status wins while the session belongs to the
 * task's latest run.
 */
export function resolveEffectiveCloudStatus(
  task: Task,
  session:
    | { taskRunId?: string | null; cloudStatus?: TaskRunStatus | null }
    | null
    | undefined,
): TaskRunStatus | null {
  const taskRunStatus = task.latest_run?.status ?? null;
  const taskRunId = task.latest_run?.id;
  const sessionMatchesLatestRun =
    !!taskRunId && session?.taskRunId === taskRunId;
  return sessionMatchesLatestRun
    ? isTerminalStatus(taskRunStatus)
      ? taskRunStatus
      : (session?.cloudStatus ?? taskRunStatus)
    : (taskRunStatus ?? session?.cloudStatus ?? null);
}

export interface CloudRunStateResult {
  prUrl: string | null;
  effectiveBranch: string | null;
  repo: string | null;
  cloudStatus: string | null;
  isRunActive: boolean;
}

export function deriveCloudRunState(
  task: Task,
  session: CloudRunSessionLike | null | undefined,
  prUrl: string | null,
): CloudRunStateResult {
  const branch = task.latest_run?.branch ?? null;
  const cloudBranch = session?.cloudBranch ?? null;
  const effectiveBranch = branch ?? cloudBranch;
  const repo = task.repository ?? null;

  const cloudStatus = resolveEffectiveCloudStatus(task, session);
  const isRunActive =
    cloudStatus === "queued" ||
    cloudStatus === "in_progress" ||
    (cloudStatus === null && session != null);

  return { prUrl, effectiveBranch, repo, cloudStatus, isRunActive };
}

export type { ChangedFile };
