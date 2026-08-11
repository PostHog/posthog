import { isTerminalStatus, type TaskRunEnvironment } from "@posthog/shared";

/**
 * Where a task's latest run lives, and whether mobile can act on it.
 *
 * - `cloud`: the normal case — mobile owns the session and every control works.
 * - `local-terminal`: the run happened on the user's desktop and has finished,
 *   so mobile can pick the task up by starting a fresh cloud run from it.
 * - `local-active`: the run is still going on the desktop. Mobile must not
 *   start a competing cloud run, so its controls are locked until it ends.
 */
export type TaskRunPlacement = "cloud" | "local-active" | "local-terminal";

interface TaskRunPlacementInput {
  latest_run?: {
    environment?: TaskRunEnvironment;
    status?: string | null;
  } | null;
}

export function classifyTaskRunPlacement(
  task: TaskRunPlacementInput | null | undefined,
): TaskRunPlacement {
  const run = task?.latest_run;
  // A task with no run at all is a cloud task waiting to start: mobile creates
  // the run itself, so nothing about it is desktop-owned.
  if (run?.environment !== "local") return "cloud";
  return isTerminalStatus(run.status) ? "local-terminal" : "local-active";
}

/** True when the task's latest run happened on the user's desktop. */
export function isLocalRunTask(
  task: TaskRunPlacementInput | null | undefined,
): boolean {
  return classifyTaskRunPlacement(task) !== "cloud";
}

export interface LocalRunState {
  /** One-line notice pinned above the thread. */
  notice: string;
  /** Label on the full-width bar that stands in for the composer. */
  actionLabel: string;
  /** False while the desktop run is still live — the bar is shown disabled. */
  canContinue: boolean;
}

/**
 * Everything the task detail screen needs to say about a desktop-owned run,
 * from one switch so the notice and the action can never disagree.
 *
 * A desktop-owned run has no cloud session behind it, so typing into the
 * composer could only ever fail with "No active session". Mobile replaces the
 * composer with the single move that does work — starting a fresh cloud run —
 * and disables it until the desktop run has actually ended, so the two never
 * race. Cloud tasks return null: no notice, and the real composer stays.
 */
export function getLocalRunState(
  placement: TaskRunPlacement,
): LocalRunState | null {
  switch (placement) {
    case "cloud":
      return null;
    case "local-active":
      return {
        notice: "This task is running on your desktop",
        actionLabel: "Running on desktop…",
        canContinue: false,
      };
    case "local-terminal":
      return {
        notice: "This task last ran on your desktop",
        actionLabel: "Continue in cloud",
        canContinue: true,
      };
  }
}
