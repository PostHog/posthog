import type { Task } from "@posthog/shared/domain-types";
import {
  type CellEligibilityInput,
  isTaskEligibleForCell,
} from "./eligibility";

export const RECENT_WINDOW_MS = 2 * 60 * 60 * 1000;

export function getLastActivity(task: Task): number {
  const taskTime = new Date(task.updated_at).getTime();
  const runTime = task.latest_run?.updated_at
    ? new Date(task.latest_run.updated_at).getTime()
    : 0;
  return Math.max(taskTime, runTime);
}

export interface AutofillInput extends CellEligibilityInput {
  emptySlots: number;
  nowMs: number;
  recentWindowMs?: number;
}

export function selectAutofillCandidates(
  tasks: Task[],
  input: AutofillInput,
): string[] {
  const recentWindowMs = input.recentWindowMs ?? RECENT_WINDOW_MS;
  const cutoff = input.nowMs - recentWindowMs;
  return tasks
    .filter(
      (task) =>
        isTaskEligibleForCell(task, input) && getLastActivity(task) >= cutoff,
    )
    .sort((a, b) => getLastActivity(b) - getLastActivity(a))
    .slice(0, input.emptySlots)
    .map((task) => task.id);
}
