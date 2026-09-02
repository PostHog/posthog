import { z } from "zod";

export const autoresearchDirectionSchema = z.enum(["maximize", "minimize"]);
export type AutoresearchDirection = z.infer<typeof autoresearchDirectionSchema>;

export const autoresearchRunStatusSchema = z.enum([
  "running",
  // User chose to halt the loop; only the user resumes it.
  "paused",
  // The loop hit a recoverable obstacle (session died, usage limit, app
  // restart) and resumes automatically once the obstacle clears.
  "interrupted",
  "completed",
  "stopped",
  "failed",
]);
export type AutoresearchRunStatus = z.infer<typeof autoresearchRunStatusSchema>;

export const autoresearchEndReasonSchema = z.enum([
  "target-reached",
  "max-iterations",
  "stopped-by-user",
  "missing-report",
]);
export type AutoresearchEndReason = z.infer<typeof autoresearchEndReasonSchema>;

export const autoresearchInterruptionReasonSchema = z.enum([
  "session-error",
  "rate-limited",
  "send-failed",
  "app-restart",
]);
export type AutoresearchInterruptionReason = z.infer<
  typeof autoresearchInterruptionReasonSchema
>;

export const AUTORESEARCH_MAX_ITERATIONS_LIMIT = 200;

export const autoresearchConfigSchema = z.object({
  taskId: z.string().min(1),
  direction: autoresearchDirectionSchema,
  /** Optional value at which the run auto-completes. */
  targetValue: z.number().finite().nullable().default(null),
  maxIterations: z
    .number()
    .int()
    .min(1)
    .max(AUTORESEARCH_MAX_ITERATIONS_LIMIT)
    .default(10),
  /**
   * Stage configuration. When the implement and measure stages differ (in
   * model or effort), each iteration runs as two turns: an
   * ideation/implementation turn on the implement stage and a measurement
   * turn on the measure stage, typically with a cheaper model or effort. Measuring
   * is tool calls, not thinking). When the stages are identical, iterations
   * are single turns. Null fields mean "leave the session's current value
   * alone".
   */
  implementModel: z.string().min(1).nullable().default(null),
  measureModel: z.string().min(1).nullable().default(null),
  implementEffort: z.string().min(1).nullable().default(null),
  measureEffort: z.string().min(1).nullable().default(null),
  /**
   * Free-form instructions for the agent: what to optimize, how to measure
   * the metric, and any constraints to respect. The metric itself is not
   * configured anywhere. The agent names it in its reports based on this
   * brief.
   */
  instructions: z.string().trim().min(1),
});
export type AutoresearchConfig = z.infer<typeof autoresearchConfigSchema>;
export type AutoresearchConfigInput = z.input<typeof autoresearchConfigSchema>;

/**
 * The part of a run config a user settles before the task exists: everything
 * except the task id and the instructions, which are the new task's prompt.
 */
export const autoresearchDraftConfigSchema = autoresearchConfigSchema.omit({
  taskId: true,
  instructions: true,
});
export type AutoresearchDraftConfig = z.infer<
  typeof autoresearchDraftConfigSchema
>;

export const autoresearchIterationSchema = z.object({
  /** 1-based iteration number. */
  index: z.number().int().min(1),
  /** Metric value the agent reported for this iteration. */
  value: z.number().finite(),
  /** Best value observed up to and including this iteration. */
  bestValue: z.number().finite(),
  /** Change from the previous iteration's value; null for the first. */
  delta: z.number().finite().nullable(),
  /** Agent's one-line description of what it changed. */
  summary: z.string().nullable(),
  hypothesis: z.string().nullable().default(null),
  plan: z.string().nullable().default(null),
  approach: z.string().nullable().default(null),
  at: z.number(),
});
export type AutoresearchIteration = z.infer<typeof autoresearchIterationSchema>;

export const autoresearchResearchFindingSchema = z.object({
  index: z.number().int().min(1),
  summary: z.string().min(1),
  finding: z.string().min(1),
  nextStep: z.string().nullable(),
  area: z.string().nullable().default(null),
  at: z.number(),
});
export type AutoresearchResearchFinding = z.infer<
  typeof autoresearchResearchFindingSchema
>;

export function isTerminalRunStatus(status: AutoresearchRunStatus): boolean {
  return status === "completed" || status === "stopped" || status === "failed";
}

/**
 * Which half of a split iteration the loop is waiting on. Null for
 * single-turn runs and for the baseline turn of split runs.
 */
export const autoresearchPhaseSchema = z.enum(["implement", "measure"]);
export type AutoresearchPhase = z.infer<typeof autoresearchPhaseSchema>;

export const autoresearchPauseIntervalSchema = z.object({
  startedAt: z.number(),
  endedAt: z.number(),
});
export type AutoresearchPauseInterval = z.infer<
  typeof autoresearchPauseIntervalSchema
>;

export const autoresearchRunSchema = z.object({
  id: z.string().min(1),
  config: autoresearchConfigSchema,
  status: autoresearchRunStatusSchema,
  /**
   * Metric label derived from the agent's reports (the `name:` line), e.g.
   * "bundle size (kB)". Null until the first named report arrives.
   */
  metricName: z.string().nullable().default(null),
  /**
   * The metric's unit as reported by the agent (the `unit:` line), e.g.
   * "kB", "ms", "%". Rendered after every value; null for unitless counts.
   */
  metricUnit: z.string().nullable().default(null),
  phase: autoresearchPhaseSchema.nullable().default(null),
  /**
   * The session model/effort selected when the run started, captured so
   * split runs can restore them when they pause or end instead of leaving
   * the session pinned on a stage's values. Null when unknown (e.g.
   * composer runs whose session did not yet exist at registration).
   */
  originalModel: z.string().nullable().default(null),
  originalEffort: z.string().nullable().default(null),
  researchFindings: z.array(autoresearchResearchFindingSchema).default([]),
  iterations: z.array(autoresearchIterationSchema),
  startedAt: z.number(),
  pausedAt: z.number().nullable().optional(),
  pausedDurationMs: z.number().min(0).optional(),
  pauseIntervals: z.array(autoresearchPauseIntervalSchema).optional(),
  endedAt: z.number().nullable(),
  endReason: autoresearchEndReasonSchema.nullable(),
  interruptedReason: autoresearchInterruptionReasonSchema
    .nullable()
    .default(null),
  lastError: z.string().nullable(),
});
export type AutoresearchRun = z.infer<typeof autoresearchRunSchema>;

/**
 * Restore a run from its persisted JSON blob. Unparseable rows (corrupt or
 * from an incompatible future version) restore as null and are skipped.
 * A run persisted as "running" comes back as an app-restart interruption:
 * the loop that drove it died with the process that persisted it.
 */
export function parseStoredAutoresearchRun(
  data: string,
): AutoresearchRun | null {
  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch {
    return null;
  }
  const parsed = autoresearchRunSchema.safeParse(raw);
  if (!parsed.success) return null;
  let run = parsed.data;
  if (run.status === "paused" && run.pausedAt === undefined) {
    run = { ...run, pausedAt: Date.now(), pausedDurationMs: 0 };
  }
  if (run.status !== "running") return run;
  return {
    ...run,
    status: "interrupted",
    interruptedReason: "app-restart",
    pausedAt: Date.now(),
    pausedDurationMs: run.pausedDurationMs ?? 0,
  };
}

/** A metric report parsed from the agent's reply. */
export interface AutoresearchReport {
  value: number;
  /** The agent's short label for the metric, e.g. "bundle size". */
  name: string | null;
  /** The metric's unit, e.g. "kB", "ms", "%"; null for unitless counts. */
  unit: string | null;
  summary: string | null;
  hypothesis: string | null;
  plan: string | null;
  approach: string | null;
}

export interface AutoresearchResearchReport {
  summary: string;
  finding: string;
  nextStep: string | null;
  area: string | null;
}

export interface AutoresearchPlanReport {
  hypothesis: string;
  plan: string;
  approach: string;
}
