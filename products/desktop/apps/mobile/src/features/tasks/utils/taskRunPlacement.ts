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

export interface LocalRunBannerState {
  message: string;
  actionLabel: string;
  /** False while the desktop run is still live — the action is shown disabled. */
  canContinue: boolean;
}

/**
 * Copy and enablement for the task-detail banner. Returns null for cloud
 * tasks, which get no banner at all.
 */
export function getLocalRunBannerState(
  placement: TaskRunPlacement,
): LocalRunBannerState | null {
  switch (placement) {
    case "cloud":
      return null;
    case "local-active":
      return {
        message: "This task is running on your desktop",
        actionLabel: "Running on desktop",
        canContinue: false,
      };
    case "local-terminal":
      return {
        message: "This task last ran on your desktop",
        actionLabel: "Continue in cloud",
        canContinue: true,
      };
  }
}

export interface ComposerLock {
  /** Stands in for the composer placeholder while input is refused. */
  hint: string;
}

/**
 * Whether the composer accepts input, from the same placement the banner reads.
 *
 * A desktop-owned run has no cloud session behind it, so a send would fail with
 * "No active session" only after the user typed a whole message. Refuse the
 * input up front and point at the way forward instead. Cloud tasks return null:
 * the composer is open and the caller keeps its own placeholder.
 */
export function getComposerLock(
  placement: TaskRunPlacement,
): ComposerLock | null {
  switch (placement) {
    case "cloud":
      return null;
    case "local-active":
      // "Continue in cloud" isn't available yet -- the banner's action is
      // disabled until the desktop run ends -- so don't suggest it.
      return { hint: "Wait for the desktop run to finish" };
    case "local-terminal":
      return { hint: "Continue in cloud to keep working from here" };
  }
}
