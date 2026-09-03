import type {
  LlmSkillCreatedBy,
  LlmSkillListItem,
  ScoutConfig,
  ScoutPauseReason,
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

/**
 * How a scout came to be in its current on/off state. `enabled` alone cannot
 * tell "someone switched this off" from "the platform switched it off", and it
 * says nothing at all about a scout that is still running but already flagged
 * for auto-pause.
 */
type ScoutLifecycle =
  | "active"
  /** Still running, but the system has flagged it. See `willPause`. */
  | "warned"
  | "paused_by_user"
  | "paused_by_system";

export interface ScoutLifecycleState {
  lifecycle: ScoutLifecycle;
  reason: ScoutPauseReason | null;
  /** Badge text, or null when there is nothing worth flagging on the row. */
  label: string | null;
  /** What happened and how to get the scout running again; null when healthy. */
  explanation: string | null;
  /** The system stopped this scout — switching it back on resumes it. */
  isSystemPaused: boolean;
  /** The scout still runs, but the system has flagged it. */
  isWarned: boolean;
  /**
   * The warning actually advances to a pause. False for a `no_output` warning,
   * which the sweep raises for a look but never escalates: silence alone never
   * pauses a scout, because a watchdog's silence is the job.
   */
  willPause: boolean;
  /** ISO timestamp of the transition into this state, when the backend has one. */
  changedAt: string | null;
  consecutiveFailureCount: number;
  /**
   * Null when the backend never sent the field, which is not the same as false:
   * a PATCH it does not understand cannot persist, so the control has nothing to
   * write and should not be offered.
   */
  autoPauseExempt: boolean | null;
}

function failureCountClause(count: number): string {
  return count > 1 ? `${count} runs in a row failed` : "its runs kept failing";
}

function warnedCopy(
  reason: ScoutPauseReason | null,
  failureCount: number,
): { label: string; explanation: string; willPause: boolean } {
  switch (reason) {
    case "ignored":
      return {
        label: "Pausing soon",
        explanation:
          "Its findings have been going unacted on, so the inactivity sweep will pause this scout soon. Act on a finding, or exempt it from inactivity pauses, to keep it running.",
        willPause: true,
      };
    case "no_output":
      return {
        label: "Quiet",
        explanation:
          "This scout has surfaced nothing lately, so the inactivity sweep flagged it for a look. Staying quiet on its own never pauses a scout, so nothing happens unless someone acts.",
        willPause: false,
      };
    case "repeated_failures":
      return {
        label: "Pausing soon",
        explanation: `PostHog will pause this scout soon because ${failureCountClause(failureCount)}. Fix the skill to keep it running.`,
        willPause: true,
      };
    default:
      return {
        label: "Pausing soon",
        explanation:
          "PostHog is about to pause this scout. Exempt it from inactivity pauses to keep it running.",
        willPause: true,
      };
  }
}

function systemPausedExplanation(
  reason: ScoutPauseReason | null,
  failureCount: number,
): string {
  switch (reason) {
    case "ignored":
      return "PostHog paused this scout because its findings were going unacted on. Switch it back on to resume. It can pause again later unless its findings get acted on.";
    case "no_output":
      return "PostHog paused this scout because it stopped emitting findings. Switch it back on to resume. Staying quiet on its own will not pause it again.";
    case "repeated_failures":
      // The breaker keeps a half-open probe on this reason, so this one recovers
      // without anyone touching it. Say so, or the badge reads as terminal.
      return `PostHog paused this scout because ${failureCountClause(failureCount)}. It retries about once a day and resumes on its own once a run succeeds. Fix the skill, or switch it back on to retry right away.`;
    default:
      return "PostHog paused this scout. Switch it back on to resume.";
  }
}

/**
 * Read a scout's lifecycle out of the configs endpoint, with the copy that
 * explains it. Backends predating the lifecycle fields (and any status value we
 * do not recognise) fall back to `enabled`, which reads as a user pause — the
 * same thing the UI showed before these fields existed.
 */
export function deriveScoutLifecycle(config: ScoutConfig): ScoutLifecycleState {
  const reason = config.pause_reason ?? null;
  const failureCount = config.consecutive_failure_count ?? 0;
  const base = {
    reason,
    changedAt: config.status_changed_at ?? null,
    consecutiveFailureCount: failureCount,
    autoPauseExempt: config.auto_pause_exempt ?? null,
  };
  // A system pause always leaves the scout switched off and a warning always
  // leaves it switched on, so `enabled` breaks the tie where the two disagree.
  // That keeps an optimistically enabled scout from reading as "on, but
  // auto-paused" for the round trip it takes the server to clear the status.
  if (!config.enabled && config.status === "paused_by_system") {
    return {
      ...base,
      lifecycle: "paused_by_system",
      label: "Auto-paused",
      explanation: systemPausedExplanation(reason, failureCount),
      isSystemPaused: true,
      isWarned: false,
      willPause: false,
    };
  }
  if (config.enabled && config.status === "pending_pause") {
    const copy = warnedCopy(reason, failureCount);
    return {
      ...base,
      lifecycle: "warned",
      label: copy.label,
      explanation: copy.explanation,
      isSystemPaused: false,
      isWarned: true,
      willPause: copy.willPause,
    };
  }
  return {
    ...base,
    lifecycle: config.enabled ? "active" : "paused_by_user",
    // The switch and the dimmed row already say "off"; a badge would only
    // repeat them, and an active scout has nothing to explain.
    label: null,
    explanation: null,
    isSystemPaused: false,
    isWarned: false,
    willPause: false,
  };
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
  /**
   * Enabled scouts heading for a pause unless something changes. Excludes a
   * `no_output` warning, which never escalates — counting it here would promise
   * a pause that is not coming.
   */
  pausingSoonCount: number;
  /** Scouts the platform switched off; a user has to switch them back on. */
  systemPausedCount: number;
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
  const lifecycles = configs.map(deriveScoutLifecycle);
  const finished = completedCount + failedCount;
  return {
    totalCount: configs.length,
    enabledCount: configs.filter((config) => config.enabled).length,
    pausingSoonCount: lifecycles.filter((lifecycle) => lifecycle.willPause)
      .length,
    systemPausedCount: lifecycles.filter(
      (lifecycle) => lifecycle.isSystemPaused,
    ).length,
    runningCount,
    emittedCount,
    successRate: finished > 0 ? completedCount / finished : null,
    emitRate: runCount > 0 ? emittedRunCount / runCount : null,
  };
}

interface RunIntervalOption {
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

export const SCOUT_DAILY_AT_SCHEDULE_MODE = "daily_at";
export const SCOUT_WEEKLY_ON_SCHEDULE_MODE = "weekly_on";
export const SCOUT_CUSTOM_CRON_SCHEDULE_MODE = "custom_cron";
export const DEFAULT_SCOUT_DAILY_TIME = "09:00";
export const DEFAULT_SCOUT_WEEKLY_DAY = "1";

/** Cron day-of-week numbers, offered from Monday so the working week reads first. */
export const SCOUT_WEEKDAY_OPTIONS: { value: string; label: string }[] = [
  { value: "1", label: "Monday" },
  { value: "2", label: "Tuesday" },
  { value: "3", label: "Wednesday" },
  { value: "4", label: "Thursday" },
  { value: "5", label: "Friday" },
  { value: "6", label: "Saturday" },
  { value: "0", label: "Sunday" },
];

interface ScoutScheduleFields {
  run_interval_minutes: number;
  run_cron_schedule?: string | null;
}

/**
 * "30 9 * * *" → "09:30" when the cron is a plain daily time (the shape the settings form
 * writes). Anything richer returns null and is edited as raw cron instead.
 */
export function dailyCronToTime(
  cron: string | null | undefined,
): string | null {
  const match = cron?.trim().match(/^(\d{1,2}) (\d{1,2}) \* \* \*$/);
  if (!match) return null;
  return `${match[2].padStart(2, "0")}:${match[1].padStart(2, "0")}`;
}

/** "09:30" → "30 9 * * *" — the inverse of `dailyCronToTime`. */
export function timeToDailyCron(time: string): string {
  const [hours, minutes] = time.split(":");
  return `${Number(minutes)} ${Number(hours)} * * *`;
}

/**
 * "30 9 * * 4" → `{ day: "4", time: "09:30" }` when the cron is a plain weekly slot. Cron takes
 * both 0 and 7 for Sunday; the dropdown offers 0, so 7 maps onto it.
 */
export function weeklyCronToDayTime(
  cron: string | null | undefined,
): { day: string; time: string } | null {
  const match = cron?.trim().match(/^(\d{1,2}) (\d{1,2}) \* \* ([0-7])$/);
  if (!match) return null;
  return {
    day: match[3] === "7" ? "0" : match[3],
    time: `${match[2].padStart(2, "0")}:${match[1].padStart(2, "0")}`,
  };
}

/** `("4", "09:30")` → "30 9 * * 4" — the inverse of `weeklyCronToDayTime`. */
export function dayTimeToWeeklyCron(day: string, time: string): string {
  const [hours, minutes] = time.split(":");
  return `${Number(minutes)} ${Number(hours)} * * ${day}`;
}

export function getScoutScheduleMode(config: ScoutScheduleFields): string {
  if (!config.run_cron_schedule) return String(config.run_interval_minutes);
  if (dailyCronToTime(config.run_cron_schedule))
    return SCOUT_DAILY_AT_SCHEDULE_MODE;
  if (weeklyCronToDayTime(config.run_cron_schedule))
    return SCOUT_WEEKLY_ON_SCHEDULE_MODE;
  return SCOUT_CUSTOM_CRON_SCHEDULE_MODE;
}

export function getScoutScheduleOptions(
  config: ScoutScheduleFields,
): { value: string; label: string }[] {
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
  options.push({
    value: SCOUT_DAILY_AT_SCHEDULE_MODE,
    label: "Daily at a set time",
  });
  options.push({
    value: SCOUT_WEEKLY_ON_SCHEDULE_MODE,
    label: "Weekly on a set day",
  });
  options.push({
    value: SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
    label: "Custom cron",
  });
  return options;
}

/** Longest cron expression the config API stores. */
export const SCOUT_CRON_MAX_LENGTH = 100;

/** Shortest gap the scheduler allows between two runs, the same floor as `run_interval_minutes`. */
const SCOUT_CRON_MIN_GAP_MINUTES = 30;

const CRON_MONTH_NAMES = [
  "jan",
  "feb",
  "mar",
  "apr",
  "may",
  "jun",
  "jul",
  "aug",
  "sep",
  "oct",
  "nov",
  "dec",
];
const CRON_DAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

type CronFieldParse =
  | { kind: "values"; values: number[] }
  | { kind: "unmodeled" }
  | { kind: "invalid" };

function cronFieldNumber(
  token: string,
  offset: number,
  names: string[] | undefined,
): number | null {
  const named = names?.indexOf(token.toLowerCase());
  if (named !== undefined && named >= 0) return named + offset;
  return /^\d{1,2}$/.test(token) ? Number(token) : null;
}

/**
 * The values a single cron field matches. `unmodeled` covers the syntax this check does not
 * model (`L`, `W`, `#`, `?`): the backend decides those, because a client that guessed would
 * refuse an expression the scheduler accepts.
 */
function parseCronField(
  field: string,
  min: number,
  max: number,
  names?: string[],
): CronFieldParse {
  if (!field || /[^0-9a-zA-Z*/,-]/.test(field)) return { kind: "unmodeled" };
  const values = new Set<number>();
  for (const part of field.split(",")) {
    const [spec, stepToken, ...extra] = part.split("/");
    if (extra.length > 0 || spec === undefined) return { kind: "invalid" };
    const step = stepToken === undefined ? 1 : Number(stepToken);
    if (!Number.isInteger(step) || step < 1) return { kind: "invalid" };
    let from = min;
    let to = max;
    if (spec !== "*") {
      const bounds = spec.split("-");
      if (bounds.length > 2) return { kind: "invalid" };
      const parsed = bounds.map((token) =>
        cronFieldNumber(token, min === 0 ? 0 : 1, names),
      );
      // A token with letters that is no month or day name is syntax this check does not model,
      // like the "L" croniter takes for the last day of the month.
      if (
        parsed.some(
          (value, index) => value === null && /[a-z]/i.test(bounds[index]),
        )
      )
        return { kind: "unmodeled" };
      if (parsed.some((value) => value === null || value < min || value > max))
        return { kind: "invalid" };
      from = parsed[0] as number;
      // "5/10" is an open-ended step from 5, while a bare "5" is that one value.
      to =
        bounds.length === 2
          ? (parsed[1] as number)
          : stepToken === undefined
            ? from
            : max;
      // A wrapping range like "22-2" is an extension some parsers take and others reject.
      if (to < from) return { kind: "unmodeled" };
    }
    for (let value = from; value <= to; value += step) values.add(value);
  }
  return { kind: "values", values: [...values].sort((a, b) => a - b) };
}

/**
 * Why `expression` is not an acceptable scout cron schedule, or null when it is. Mirrors the four
 * rules the config API applies (`cron_schedule_error`) so the picker rejects a typo before the
 * PATCH. Expressions using syntax this check does not model pass and are left to the backend.
 */
export function scoutCronScheduleError(expression: string): string | null {
  const expr = expression.trim();
  if (expr.length > SCOUT_CRON_MAX_LENGTH)
    return `Cron expressions must be ${SCOUT_CRON_MAX_LENGTH} characters or fewer.`;
  const fields = expr.split(/\s+/);
  const invalidShape = "Enter a five-field cron expression, like 0 9 * * 1-5.";
  if (fields.length !== 5) return invalidShape;
  const minutes = parseCronField(fields[0], 0, 59);
  const hours = parseCronField(fields[1], 0, 23);
  const daysOfMonth = parseCronField(fields[2], 1, 31);
  const months = parseCronField(fields[3], 1, 12, CRON_MONTH_NAMES);
  const daysOfWeek = parseCronField(fields[4], 0, 7, CRON_DAY_NAMES);
  if (
    [minutes, hours, daysOfMonth, months, daysOfWeek].some(
      (field) => field.kind === "invalid",
    )
  )
    return invalidShape;
  // A day-of-month no month in the set reaches kills the schedule, whatever the weekday field
  // says: croniter refuses "0 0 31 2 MON" the same as "0 0 31 2 *".
  if (
    fields[2] !== "*" &&
    daysOfMonth.kind === "values" &&
    months.kind === "values"
  ) {
    const occurs = months.values.some((month) =>
      daysOfMonth.values.some((day) => day <= DAYS_IN_MONTH[month - 1]),
    );
    if (!occurs)
      return "This schedule never matches a real date. Check the day and month.";
  }
  if (minutes.kind === "values" && hours.kind === "values") {
    const slots = hours.values.flatMap((hour) =>
      minutes.values.map((minute) => hour * 60 + minute),
    );
    const gaps = slots.slice(1).map((slot, index) => slot - slots[index]);
    // A schedule that runs every day also runs across midnight, so the last slot of one day and
    // the first of the next are one more gap. A day-restricted schedule can skip days, so how far
    // its wrap reaches is left to the backend.
    if (fields[2] === "*" && fields[4] === "*")
      gaps.push(slots[0] + 1440 - slots[slots.length - 1]);
    if (gaps.some((gap) => gap < SCOUT_CRON_MIN_GAP_MINUTES))
      return `Runs must be at least ${SCOUT_CRON_MIN_GAP_MINUTES} minutes apart.`;
  }
  return null;
}

/** Short form for row badges: "hourly", "every 3h". */
export function formatRunIntervalShort(minutes: number): string {
  if (minutes === 60) return "hourly";
  if (minutes === 1440) return "daily";
  if (minutes % 1440 === 0) return `every ${minutes / 1440}d`;
  if (minutes % 60 === 0) return `every ${minutes / 60}h`;
  return `every ${minutes}m`;
}

/**
 * Short schedule label for row badges: "daily at 09:00", "thursdays at 08:30", the raw expression
 * for a cron the presets cannot name, and the rolling cadence when the scout runs on one.
 */
export function formatScoutScheduleShort(config: ScoutScheduleFields): string {
  const dailyTime = dailyCronToTime(config.run_cron_schedule);
  if (dailyTime) return `daily at ${dailyTime}`;
  const weekly = weeklyCronToDayTime(config.run_cron_schedule);
  if (weekly) {
    const day = SCOUT_WEEKDAY_OPTIONS.find(
      (option) => option.value === weekly.day,
    );
    if (day) return `${day.label.toLowerCase()}s at ${weekly.time}`;
  }
  if (config.run_cron_schedule) return config.run_cron_schedule;
  return formatRunIntervalShort(config.run_interval_minutes);
}

/**
 * Enabled scouts first, then the ones the system switched off (they need a
 * human to switch them back on, so they lead the off-block), then the rest
 * alphabetically.
 */
export function sortConfigsForDisplay(configs: ScoutConfig[]): ScoutConfig[] {
  return configs
    .map((config) => ({
      config,
      systemPaused: deriveScoutLifecycle(config).isSystemPaused,
      name: prettifyScoutSkillName(config.skill_name),
    }))
    .sort((a, b) => {
      if (a.config.enabled !== b.config.enabled) {
        return a.config.enabled ? -1 : 1;
      }
      if (a.systemPaused !== b.systemPaused) return a.systemPaused ? -1 : 1;
      return a.name.localeCompare(b.name);
    })
    .map((entry) => entry.config);
}
