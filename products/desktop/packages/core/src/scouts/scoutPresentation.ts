import type {
  LlmSkillCreatedBy,
  LlmSkillListItem,
  ScoutConfig,
  ScoutRun,
} from "@posthog/api-client/posthog-client";

// Single source of truth lives in `@posthog/shared` so `buildScoutDeeplink`
// (which cannot import core) and the UI share one slug implementation.
export { scoutSkillNameFromSlug, scoutSkillSlug } from "@posthog/shared";

export type ScoutOrigin = "canonical" | "custom";

/**
 * Origin comes straight from the configs endpoint's `scout_origin` field, which
 * the backend computes from the skill's `seeded_by` metadata. Older backends
 * omit the field; treat those scouts as custom.
 */
export function getScoutOrigin(
  config: Pick<ScoutConfig, "scout_origin"> | null | undefined,
): ScoutOrigin {
  return config?.scout_origin === "canonical" ? "canonical" : "custom";
}

/** "signals-scout-error-tracking" → "Error tracking" */
export function prettifyScoutSkillName(skillName: string): string {
  const cleaned = skillName
    .replace(/^signals-scout-/, "")
    .replace(/[-_]/g, " ")
    .trim();
  if (!cleaned) return skillName;
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

/** Skill name → author of the backing `signals-scout-*` skill's latest version. */
export type ScoutCreatorIndex = Map<string, LlmSkillCreatedBy>;

/**
 * The configs endpoint carries no creator, so authorship comes from the
 * backing skill (the scout IS the skill). Canonical seeds are created with no
 * `created_by`, so absence from the index means "not hand-authored by anyone".
 */
export function buildScoutCreatorIndex(
  skills: Pick<LlmSkillListItem, "name" | "created_by" | "is_latest">[],
): ScoutCreatorIndex {
  const index: ScoutCreatorIndex = new Map();
  for (const skill of skills) {
    if (!skill.is_latest || !skill.created_by) continue;
    index.set(skill.name, skill.created_by);
  }
  return index;
}

/** The slice of the current user the creator filter needs. */
export interface ScoutCreatorUser {
  id?: number;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
}

export function isScoutCreatedByUser(
  creator: LlmSkillCreatedBy | null | undefined,
  user: ScoutCreatorUser | null | undefined,
): boolean {
  if (!creator || !user) return false;
  if (creator.id !== undefined && user.id !== undefined) {
    return creator.id === user.id;
  }
  // Older payloads may omit the numeric id; emails are unique per instance.
  const creatorEmail = creator.email?.trim().toLowerCase();
  const userEmail = user.email?.trim().toLowerCase();
  return !!creatorEmail && creatorEmail === userEmail;
}

export function scoutCreatorDisplayName(
  creator: Pick<LlmSkillCreatedBy, "first_name" | "last_name" | "email">,
): string {
  const name = [creator.first_name, creator.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
  return name || creator.email?.trim() || "Unknown user";
}

/**
 * Stable identity for a creator across the option list and the per-config
 * lookup: the numeric user id when present, else the lowercased email.
 */
export function scoutCreatorKey(
  creator: Pick<LlmSkillCreatedBy, "id" | "email"> | null | undefined,
): string | null {
  if (!creator) return null;
  if (typeof creator.id === "number") return `id:${creator.id}`;
  const email = creator.email?.trim().toLowerCase();
  return email ? `email:${email}` : null;
}

export interface ScoutCreatorOption {
  key: string;
  label: string;
  isCurrentUser: boolean;
}

/**
 * Distinct authors across the fleet for a "Created by" picker: the current
 * user pinned first (offered even with nothing authored yet, so "just mine"
 * is always selectable), then the other authors A–Z. Canonical seeds carry no
 * author, so they never contribute an option.
 */
export function listScoutCreatorOptions(
  index: ScoutCreatorIndex,
  currentUser: ScoutCreatorUser | null | undefined,
): ScoutCreatorOption[] {
  const byKey = new Map<string, ScoutCreatorOption>();
  for (const creator of index.values()) {
    const key = scoutCreatorKey(creator);
    if (!key || byKey.has(key)) continue;
    const isCurrentUser = isScoutCreatedByUser(creator, currentUser);
    byKey.set(key, {
      key,
      label: isCurrentUser
        ? `${scoutCreatorDisplayName(creator)} (you)`
        : scoutCreatorDisplayName(creator),
      isCurrentUser,
    });
  }
  const options = [...byKey.values()];
  if (currentUser && !options.some((option) => option.isCurrentUser)) {
    const key = scoutCreatorKey(currentUser);
    if (key) {
      options.push({
        key,
        label: `${scoutCreatorDisplayName(currentUser)} (you)`,
        isCurrentUser: true,
      });
    }
  }
  options.sort((a, b) => {
    if (a.isCurrentUser !== b.isCurrentUser) return a.isCurrentUser ? -1 : 1;
    return a.label.localeCompare(b.label);
  });
  return options;
}

export type ScoutRunStatus =
  | "completed"
  | "failed"
  | "running"
  | "queued"
  | "unknown";

export function normalizeRunStatus(status: string): ScoutRunStatus {
  const lower = status.toLowerCase();
  if (lower === "completed") return "completed";
  if (lower === "failed" || lower === "cancelled") return "failed";
  if (lower === "in_progress") return "running";
  if (lower === "queued" || lower === "not_started") return "queued";
  return "unknown";
}

export function runDurationSeconds(run: ScoutRun, now: Date): number | null {
  if (!run.started_at) return null;
  const started = new Date(run.started_at).getTime();
  if (Number.isNaN(started)) return null;
  const ended = run.completed_at
    ? new Date(run.completed_at).getTime()
    : now.getTime();
  if (Number.isNaN(ended) || ended < started) return null;
  return (ended - started) / 1000;
}

export function formatRunDuration(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  const hours = Math.floor(mins / 60);
  const remainMins = mins % 60;
  return remainMins > 0 ? `${hours}h ${remainMins}m` : `${hours}h`;
}

/**
 * Scout runs are hard-killed at the ~31-minute Temporal activity deadline and
 * surface as bare "failed" with an empty summary and no error field (scouts-ui
 * api gap 2). Until the serializer carries a failure kind, infer a timeout
 * from the run length.
 */
const TIMEOUT_THRESHOLD_SECONDS = 29 * 60;

export type ScoutRunFailureKind = "timed_out" | "error";

export function deriveRunFailureKind(
  run: ScoutRun,
  now: Date,
): ScoutRunFailureKind | null {
  if (normalizeRunStatus(run.status) !== "failed") return null;
  const duration = runDurationSeconds(run, now);
  if (duration !== null && duration >= TIMEOUT_THRESHOLD_SECONDS) {
    return "timed_out";
  }
  return "error";
}

/**
 * A SIGKILL mid-run can strand a TaskRun in IN_PROGRESS with no self-heal
 * (posthog scouts dogfooding issue 09). Past the run deadline we can be sure
 * the run is not actually still working.
 */
const STUCK_THRESHOLD_SECONDS = 35 * 60;

export function isRunStuck(run: ScoutRun, now: Date): boolean {
  if (normalizeRunStatus(run.status) !== "running") return false;
  const duration = runDurationSeconds(run, now);
  return duration !== null && duration >= STUCK_THRESHOLD_SECONDS;
}

/**
 * Single classification for "how did this run go", combining status, failure
 * kind, and emission count. Drives the per-run outcome boxes and tooltips.
 */
export type ScoutRunOutcome =
  | "emitted"
  | "quiet"
  | "error"
  | "timed_out"
  | "running"
  | "stuck"
  | "queued"
  | "unknown";

export function deriveRunOutcome(run: ScoutRun, now: Date): ScoutRunOutcome {
  const status = normalizeRunStatus(run.status);
  if (status === "completed") {
    return (run.emitted_count ?? 0) > 0 ? "emitted" : "quiet";
  }
  if (status === "failed") {
    return deriveRunFailureKind(run, now) === "timed_out"
      ? "timed_out"
      : "error";
  }
  if (status === "running") return isRunStuck(run, now) ? "stuck" : "running";
  if (status === "queued") return "queued";
  return "unknown";
}

export function scoutRunOutcomeLabel(run: ScoutRun, now: Date): string {
  switch (deriveRunOutcome(run, now)) {
    case "emitted": {
      const count = run.emitted_count ?? 0;
      return `${count} signal${count === 1 ? "" : "s"} emitted`;
    }
    case "quiet":
      return "0 signals emitted";
    case "error":
      return "failed";
    case "timed_out":
      return "timed out";
    case "running":
      return "running now";
    case "stuck":
      return "running past the deadline – may be stuck";
    case "queued":
      return "queued";
    case "unknown":
      return run.status;
  }
}

export type ScoutRunFilter = "all" | "emitted" | "quiet" | "failed";

export function runMatchesFilter(
  run: ScoutRun,
  filter: ScoutRunFilter,
): boolean {
  const status = normalizeRunStatus(run.status);
  switch (filter) {
    case "all":
      return true;
    case "emitted":
      return (run.emitted_count ?? 0) > 0;
    case "quiet":
      return status === "completed" && (run.emitted_count ?? 0) === 0;
    case "failed":
      return status === "failed";
  }
}

export interface ScoutRollup {
  runCount: number;
  completedCount: number;
  failedCount: number;
  emittedCount: number;
  latestRun: ScoutRun | null;
  runningRun: ScoutRun | null;
  /** This scout's runs in the window, oldest first (timeline order). */
  runs: ScoutRun[];
}

function emptyRollup(): ScoutRollup {
  return {
    runCount: 0,
    completedCount: 0,
    failedCount: 0,
    emittedCount: 0,
    latestRun: null,
    runningRun: null,
    runs: [],
  };
}

/**
 * Client-side rollup over the most recent fleet runs. The runs endpoint has
 * no per-scout filter or aggregate stats yet (scouts-ui api gaps 1 and 3) and
 * caps at 100 rows, so these numbers describe "the recent window we can see",
 * not all time. Surface them with that framing.
 */
export function computeScoutRollups(
  runs: ScoutRun[],
): Map<string, ScoutRollup> {
  const rollups = new Map<string, ScoutRollup>();
  for (const run of runs) {
    let rollup = rollups.get(run.skill_name);
    if (!rollup) {
      rollup = emptyRollup();
      rollups.set(run.skill_name, rollup);
    }
    rollup.runCount += 1;
    const status = normalizeRunStatus(run.status);
    if (status === "completed") rollup.completedCount += 1;
    if (status === "failed") rollup.failedCount += 1;
    rollup.emittedCount += run.emitted_count ?? 0;
    rollup.runs.push(run);
    const startedAt = run.started_at ? new Date(run.started_at).getTime() : 0;
    const latestStartedAt = rollup.latestRun?.started_at
      ? new Date(rollup.latestRun.started_at).getTime()
      : -1;
    if (startedAt > latestStartedAt) rollup.latestRun = run;
    if (status === "running" && !rollup.runningRun) rollup.runningRun = run;
  }
  for (const rollup of rollups.values()) {
    rollup.runs.sort((a, b) => {
      const aStarted = a.started_at ? new Date(a.started_at).getTime() : 0;
      const bStarted = b.started_at ? new Date(b.started_at).getTime() : 0;
      return aStarted - bStarted;
    });
  }
  return rollups;
}

export interface FleetSummary {
  totalCount: number;
  enabledCount: number;
  runningCount: number;
  emittedCount: number;
  /** Completed / (completed + failed) over the visible window, or null when no finished runs. */
  successRate: number | null;
  /** Share of runs in the window that emitted at least one signal, or null when no runs. */
  emitRate: number | null;
}

export function computeFleetSummary(
  configs: ScoutConfig[],
  rollups: Map<string, ScoutRollup>,
): FleetSummary {
  let runningCount = 0;
  let emittedCount = 0;
  let completedCount = 0;
  let failedCount = 0;
  let runCount = 0;
  let emittedRunCount = 0;
  for (const rollup of rollups.values()) {
    if (rollup.runningRun) runningCount += 1;
    emittedCount += rollup.emittedCount;
    completedCount += rollup.completedCount;
    failedCount += rollup.failedCount;
    runCount += rollup.runCount;
    for (const run of rollup.runs) {
      if ((run.emitted_count ?? 0) > 0) emittedRunCount += 1;
    }
  }
  const finished = completedCount + failedCount;
  return {
    totalCount: configs.length,
    enabledCount: configs.filter((config) => config.enabled).length,
    runningCount,
    emittedCount,
    successRate: finished > 0 ? completedCount / finished : null,
    emitRate: runCount > 0 ? emittedRunCount / runCount : null,
  };
}

export interface RunIntervalOption {
  minutes: number;
  label: string;
}

export const RUN_INTERVAL_OPTIONS: RunIntervalOption[] = [
  { minutes: 30, label: "Every 30 minutes" },
  { minutes: 60, label: "Hourly" },
  { minutes: 120, label: "Every 2 hours" },
  { minutes: 180, label: "Every 3 hours" },
  { minutes: 360, label: "Every 6 hours" },
  { minutes: 720, label: "Every 12 hours" },
  { minutes: 1440, label: "Daily" },
];

export function formatRunInterval(minutes: number): string {
  const preset = RUN_INTERVAL_OPTIONS.find(
    (option) => option.minutes === minutes,
  );
  if (preset) return preset.label;
  if (minutes % 1440 === 0) return `Every ${minutes / 1440} days`;
  if (minutes % 60 === 0) return `Every ${minutes / 60} hours`;
  return `Every ${minutes} minutes`;
}

/** Short form for row badges: "hourly", "every 3h". */
export function formatRunIntervalShort(minutes: number): string {
  if (minutes === 60) return "hourly";
  if (minutes === 1440) return "daily";
  if (minutes % 1440 === 0) return `every ${minutes / 1440}d`;
  if (minutes % 60 === 0) return `every ${minutes / 60}h`;
  return `every ${minutes}m`;
}

export function sortConfigsForDisplay(configs: ScoutConfig[]): ScoutConfig[] {
  return [...configs].sort((a, b) => {
    if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
    return prettifyScoutSkillName(a.skill_name).localeCompare(
      prettifyScoutSkillName(b.skill_name),
    );
  });
}
