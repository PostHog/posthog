import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  deriveRunOutcome,
  formatRunInterval,
  RUN_INTERVAL_OPTIONS,
  type ScoutLifecycle,
  type ScoutRollup,
  scoutRunOutcomeLabel,
} from "@posthog/core/scouts/scoutPresentation";
import type { ScoutRunsWindow } from "@posthog/core/scouts/scoutRunsWindow";
import type { SelectOption } from "@/features/tasks/composer/SelectSheet";

/**
 * Presentation helpers for the mobile scouts screen. Everything here is pure so
 * the screen stays a renderer; the fleet maths itself lives in
 * `@posthog/core/scouts/scoutPresentation` and is shared with desktop.
 */

/** "82%" for a rate in [0,1]; an em dash when there is nothing to rate. */
export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${Math.round(rate * 100)}%`;
}

/**
 * Whether any scout in the window is mid-run. Drives the screen's polling: the
 * fleet is otherwise static between scheduled dispatches, so a running scout is
 * the only reason to refetch on a timer.
 */
export function runsWindowHasRunningRun(
  window: ScoutRunsWindow | undefined,
  rollups: Map<string, ScoutRollup>,
): boolean {
  if (!window) return false;
  for (const rollup of rollups.values()) {
    if (rollup.runningRun) return true;
  }
  return false;
}

export interface LastRunSummary {
  /** How the run went, e.g. "3 signals emitted" or "timed out". */
  label: string;
  /** Epoch ms to render as a relative time, or null when the run has no timestamp. */
  at: number | null;
  /** True while the run is still in flight, so the row can show it as live. */
  isRunning: boolean;
}

/**
 * The one line describing a scout's most recent run in the visible window.
 * Null when the scout has not run inside the window at all — the row says so
 * rather than implying the scout never ran.
 */
export function describeLastRun(
  rollup: ScoutRollup | undefined,
  now: Date,
): LastRunSummary | null {
  const run = rollup?.latestRun;
  if (!run) return null;
  const outcome = deriveRunOutcome(run, now);
  const timestamp = run.completed_at ?? run.started_at;
  const parsed = timestamp ? new Date(timestamp).getTime() : Number.NaN;
  return {
    label: scoutRunOutcomeLabel(run, now),
    at: Number.isNaN(parsed) ? null : parsed,
    isRunning: outcome === "running" || outcome === "stuck",
  };
}

/**
 * Cadence options for the interval picker: the shared presets, plus the
 * scout's own interval when it is not one of them (a config set elsewhere must
 * still show its real cadence as the selected option).
 */
export function intervalOptions(config: ScoutConfig): SelectOption<string>[] {
  const options = RUN_INTERVAL_OPTIONS.map((option) => ({
    value: String(option.minutes),
    label: option.label,
  }));
  if (
    !RUN_INTERVAL_OPTIONS.some(
      (option) => option.minutes === config.run_interval_minutes,
    )
  ) {
    options.push({
      value: String(config.run_interval_minutes),
      label: formatRunInterval(config.run_interval_minutes),
    });
  }
  return options;
}

/** NativeWind classes for a lifecycle badge, or null when there is no badge. */
export function lifecycleBadgeClasses(
  lifecycle: ScoutLifecycle,
): { container: string; text: string } | null {
  switch (lifecycle) {
    case "paused_by_system":
      return { container: "bg-status-error/20", text: "text-status-error" };
    case "warned":
      return { container: "bg-status-warning/20", text: "text-status-warning" };
    default:
      // Active and user-paused scouts are already described by the switch and
      // the dimmed row; a badge would only repeat them.
      return null;
  }
}
