import { isTerminalStatus } from "@posthog/shared/domain-types";

export function isTaskRunning(task: {
  latest_run?: { status: string | null };
}): boolean {
  const status = task.latest_run?.status;
  return status !== undefined && !isTerminalStatus(status);
}
