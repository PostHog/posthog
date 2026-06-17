// Ported from PostHog Code desktop `packages/core/src/scouts/scoutRunsWindow.ts`
// and `scoutPresentation.ts`. Pure metrics + display helpers over scout runs and
// configs; no I/O. The runs the cloud API returns are already the newest-first,
// 100-row-capped window the desktop assembled by hand, so the cursor-pagination
// loop is dropped here – but the same window framing and labels are preserved.

import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'

import { SignalScoutConfig, SignalScoutRunStatus, SignalScoutRunSummary } from '../types'

/**
 * The window every scout stat describes. The cloud runs endpoint caps each list
 * response at 100 rows newest-first; we frame all numbers as "the recent window
 * we can see", matching desktop's fixed-window framing.
 */
export const SCOUT_RUNS_WINDOW_HOURS = 72

/** Human-friendly span the window covers, e.g. "3 days". */
export const SCOUT_RUNS_WINDOW_SPAN = ((): string => {
    if (SCOUT_RUNS_WINDOW_HOURS % 24 !== 0) {
        return `${SCOUT_RUNS_WINDOW_HOURS}h`
    }
    const days = SCOUT_RUNS_WINDOW_HOURS / 24
    return `${days} day${days === 1 ? '' : 's'}`
})()

/** Label for stats derived from a window, e.g. "last 3 days". */
export function scoutRunsWindowLabel(complete: boolean): string {
    const base = `last ${SCOUT_RUNS_WINDOW_SPAN}`
    return complete ? base : `${base} · truncated`
}

// ── Origin classification ────────────────────────────────────────────────────

/**
 * Canonical scouts shipped in the PostHog repo (products/signals/skills). The
 * configs endpoint does not yet distinguish canonical from hand-authored skills,
 * so classify by this known-name list (matches desktop `CANONICAL_SCOUT_SKILLS`).
 */
export const CANONICAL_SCOUT_SKILLS = new Set<string>([
    'signals-scout-general',
    'signals-scout-anomaly-detection',
    'signals-scout-ai-observability',
    'signals-scout-csp-violations',
    'signals-scout-data-pipelines',
    'signals-scout-error-tracking',
    'signals-scout-experiments',
    'signals-scout-feature-flags',
    'signals-scout-health-checks',
    'signals-scout-logs',
    'signals-scout-observability-gaps',
    'signals-scout-revenue-analytics',
    'signals-scout-session-replay',
    'signals-scout-surveys',
    'signals-scout-web-analytics',
])

export type ScoutOrigin = 'canonical' | 'custom'

export function getScoutOrigin(skillName: string): ScoutOrigin {
    return CANONICAL_SCOUT_SKILLS.has(skillName) ? 'canonical' : 'custom'
}

/** "signals-scout-error-tracking" → "Error tracking" */
export function prettifyScoutSkillName(skillName: string): string {
    const cleaned = skillName
        .replace(/^signals-scout-/, '')
        .replace(/[-_]/g, ' ')
        .trim()
    if (!cleaned) {
        return skillName
    }
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
}

// ── Run status / outcome ─────────────────────────────────────────────────────

export type ScoutRunStatus = 'completed' | 'failed' | 'running' | 'queued' | 'unknown'

export function normalizeRunStatus(status: SignalScoutRunStatus): ScoutRunStatus {
    if (status === 'completed') {
        return 'completed'
    }
    if (status === 'failed' || status === 'cancelled') {
        return 'failed'
    }
    if (status === 'in_progress') {
        return 'running'
    }
    if (status === 'queued' || status === 'not_started') {
        return 'queued'
    }
    return 'unknown'
}

export function runDurationSeconds(run: SignalScoutRunSummary, now: Date): number | null {
    if (!run.started_at) {
        return null
    }
    const started = new Date(run.started_at).getTime()
    if (Number.isNaN(started)) {
        return null
    }
    const ended = run.completed_at ? new Date(run.completed_at).getTime() : now.getTime()
    if (Number.isNaN(ended) || ended < started) {
        return null
    }
    return (ended - started) / 1000
}

/** Format a run's duration for display, e.g. "1m 30s". Empty string when unknown. */
export function formatRunDuration(seconds: number | null): string {
    return humanFriendlyDuration(seconds, { maxUnits: 2 })
}

/**
 * Scout runs are hard-killed at the ~31-minute Temporal activity deadline and
 * surface as bare "failed" with no error field. Until the serializer carries a
 * failure kind, infer a timeout from the run length.
 */
const TIMEOUT_THRESHOLD_SECONDS = 29 * 60

export type ScoutRunFailureKind = 'timed_out' | 'error'

export function deriveRunFailureKind(run: SignalScoutRunSummary, now: Date): ScoutRunFailureKind | null {
    if (normalizeRunStatus(run.status) !== 'failed') {
        return null
    }
    const duration = runDurationSeconds(run, now)
    if (duration !== null && duration >= TIMEOUT_THRESHOLD_SECONDS) {
        return 'timed_out'
    }
    return 'error'
}

/**
 * A SIGKILL mid-run can strand a TaskRun in IN_PROGRESS with no self-heal. Past
 * the run deadline we can be sure the run is not actually still working.
 */
const STUCK_THRESHOLD_SECONDS = 35 * 60

export function isRunStuck(run: SignalScoutRunSummary, now: Date): boolean {
    if (normalizeRunStatus(run.status) !== 'running') {
        return false
    }
    const duration = runDurationSeconds(run, now)
    return duration !== null && duration >= STUCK_THRESHOLD_SECONDS
}

export type ScoutRunOutcome = 'emitted' | 'quiet' | 'error' | 'timed_out' | 'running' | 'stuck' | 'queued' | 'unknown'

export function deriveRunOutcome(run: SignalScoutRunSummary, now: Date): ScoutRunOutcome {
    const status = normalizeRunStatus(run.status)
    if (status === 'completed') {
        return (run.emitted_count ?? 0) > 0 ? 'emitted' : 'quiet'
    }
    if (status === 'failed') {
        return deriveRunFailureKind(run, now) === 'timed_out' ? 'timed_out' : 'error'
    }
    if (status === 'running') {
        return isRunStuck(run, now) ? 'stuck' : 'running'
    }
    if (status === 'queued') {
        return 'queued'
    }
    return 'unknown'
}

export function scoutRunOutcomeLabel(run: SignalScoutRunSummary, now: Date): string {
    switch (deriveRunOutcome(run, now)) {
        case 'emitted': {
            const count = run.emitted_count ?? 0
            return `${pluralize(count, 'signal')} emitted`
        }
        case 'quiet':
            return '0 signals emitted'
        case 'error':
            return 'failed'
        case 'timed_out':
            return 'timed out'
        case 'running':
            return 'running now'
        case 'stuck':
            return 'running past the deadline – may be stuck'
        case 'queued':
            return 'queued'
        case 'unknown':
            return run.status
    }
}

// ── Per-scout rollups ────────────────────────────────────────────────────────

export interface ScoutRollup {
    runCount: number
    completedCount: number
    failedCount: number
    emittedCount: number
    latestRun: SignalScoutRunSummary | null
    runningRun: SignalScoutRunSummary | null
    /** This scout's runs in the window, oldest first (timeline order). */
    runs: SignalScoutRunSummary[]
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
    }
}

/**
 * Client-side rollup over the recent fleet runs, keyed by skill_name. The runs
 * endpoint has no per-scout filter or aggregate stats yet and caps at 100 rows,
 * so these numbers describe "the recent window we can see", not all time.
 */
export function computeScoutRollups(runs: SignalScoutRunSummary[]): Map<string, ScoutRollup> {
    const rollups = new Map<string, ScoutRollup>()
    for (const run of runs) {
        let rollup = rollups.get(run.skill_name)
        if (!rollup) {
            rollup = emptyRollup()
            rollups.set(run.skill_name, rollup)
        }
        rollup.runCount += 1
        const status = normalizeRunStatus(run.status)
        if (status === 'completed') {
            rollup.completedCount += 1
        }
        if (status === 'failed') {
            rollup.failedCount += 1
        }
        rollup.emittedCount += run.emitted_count ?? 0
        rollup.runs.push(run)
        const startedAt = run.started_at ? new Date(run.started_at).getTime() : 0
        const latestStartedAt = rollup.latestRun?.started_at ? new Date(rollup.latestRun.started_at).getTime() : -1
        if (startedAt > latestStartedAt) {
            rollup.latestRun = run
        }
        if (status === 'running' && !rollup.runningRun) {
            rollup.runningRun = run
        }
    }
    for (const rollup of rollups.values()) {
        rollup.runs.sort((a, b) => {
            const aStarted = a.started_at ? new Date(a.started_at).getTime() : 0
            const bStarted = b.started_at ? new Date(b.started_at).getTime() : 0
            return aStarted - bStarted
        })
    }
    return rollups
}

// ── Fleet summary ────────────────────────────────────────────────────────────

export interface FleetSummary {
    totalCount: number
    enabledCount: number
    runningCount: number
    emittedCount: number
    /** Completed / (completed + failed) over the window, or null when no finished runs. */
    successRate: number | null
    /** Share of runs in the window that emitted at least one signal, or null when no runs. */
    emitRate: number | null
}

export function computeFleetSummary(configs: SignalScoutConfig[], rollups: Map<string, ScoutRollup>): FleetSummary {
    let runningCount = 0
    let emittedCount = 0
    let completedCount = 0
    let failedCount = 0
    let runCount = 0
    let emittedRunCount = 0
    for (const rollup of rollups.values()) {
        if (rollup.runningRun) {
            runningCount += 1
        }
        emittedCount += rollup.emittedCount
        completedCount += rollup.completedCount
        failedCount += rollup.failedCount
        runCount += rollup.runCount
        for (const run of rollup.runs) {
            if ((run.emitted_count ?? 0) > 0) {
                emittedRunCount += 1
            }
        }
    }
    const finished = completedCount + failedCount
    return {
        totalCount: configs.length,
        enabledCount: configs.filter((config) => config.enabled).length,
        runningCount,
        emittedCount,
        successRate: finished > 0 ? completedCount / finished : null,
        emitRate: runCount > 0 ? emittedRunCount / runCount : null,
    }
}

// ── Run interval formatting ──────────────────────────────────────────────────

export interface RunIntervalOption {
    minutes: number
    label: string
}

export const RUN_INTERVAL_OPTIONS: RunIntervalOption[] = [
    { minutes: 30, label: 'Every 30 minutes' },
    { minutes: 60, label: 'Hourly' },
    { minutes: 120, label: 'Every 2 hours' },
    { minutes: 180, label: 'Every 3 hours' },
    { minutes: 360, label: 'Every 6 hours' },
    { minutes: 720, label: 'Every 12 hours' },
    { minutes: 1440, label: 'Daily' },
]

export function formatRunInterval(minutes: number): string {
    const preset = RUN_INTERVAL_OPTIONS.find((option) => option.minutes === minutes)
    if (preset) {
        return preset.label
    }
    if (minutes % 1440 === 0) {
        return `Every ${minutes / 1440} days`
    }
    if (minutes % 60 === 0) {
        return `Every ${minutes / 60} hours`
    }
    return `Every ${minutes} minutes`
}

/** Short form for row badges: "hourly", "every 3h". */
export function formatRunIntervalShort(minutes: number): string {
    if (minutes === 60) {
        return 'hourly'
    }
    if (minutes === 1440) {
        return 'daily'
    }
    if (minutes % 1440 === 0) {
        return `every ${minutes / 1440}d`
    }
    if (minutes % 60 === 0) {
        return `every ${minutes / 60}h`
    }
    return `every ${minutes}m`
}

export function sortConfigsForDisplay(configs: SignalScoutConfig[]): SignalScoutConfig[] {
    return [...configs].sort((a, b) => {
        if (a.enabled !== b.enabled) {
            return a.enabled ? -1 : 1
        }
        return prettifyScoutSkillName(a.skill_name).localeCompare(prettifyScoutSkillName(b.skill_name))
    })
}

// ── Templated chat-task prompts (ported from desktop scoutPrompts.ts) ─────────

export const SCOUT_AUTHOR_PROMPT = `I'd like to make a new scout for this PostHog project.

Use the authoring-signals-scouts skill from the PostHog MCP to guide creating a new signals scout.

First, take a quick scan of this PostHog project to ground your suggestions: skim its events, insights, dashboards, recently emitted signals, and the existing scout fleet so you understand what this product is and where automated monitoring would add value.

Then ask me what sort of scout I'd like to make, and offer a few concrete suggestions tailored to what you found (for example specific funnels, error or latency spikes, churn or activation signals, or revenue metrics worth watching) – and call out gaps the current fleet doesn't already cover. Once I pick a direction, walk me through authoring the scout end to end.

If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list to see the existing fleet) plus the read-data and insight tools to scan the project.`

export const SCOUT_FLEET_OVERVIEW_PROMPT = `How is my scout fleet performing?

Use the exploring-signals-scouts skill from the PostHog MCP to survey the signals scout fleet on this project and give me a high-level overview:

- The fleet: which scouts exist, enabled vs disabled, and their cadences
- Recent run health: success rate, failures and timeouts, anything stuck
- Output: which scouts emitted signals recently, emit rate, signal-to-noise
- Memory: notable scratchpad entries the fleet has learned
- Recommendations: anything misconfigured, noisy, or worth tuning

Lead with a short overall verdict, then per-scout notes only where something is notable. If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list, runs list, scratchpad search).`

export const SCOUT_RECENT_SIGNALS_PROMPT = `What signals have my scouts emitted recently?

Use the exploring-signals-scouts skill from the PostHog MCP to pull the most recent scout runs that emitted findings and walk me through the signals:

- What each signal says, in plain language
- Which scout emitted it, when, and its severity/confidence where available
- Whether it looks genuinely actionable or like noise

Group by scout, newest first. Close with a short note on overall signal quality and any scouts that look noisy or suspiciously silent. If the skill is unavailable, fall back to the signals-scout MCP tools directly (runs list with emitted filter, run emissions).`

/** Per-scout variant of the templated questions, scoped to one skill. */
export function buildScoutCheckinPrompt(skillName: string, displayName: string): string {
    return `How is my ${displayName} scout performing?

Use the exploring-signals-scouts skill from the PostHog MCP to dig into the \`${skillName}\` scout on this project:

- Its config: enabled, cadence, dry-run posture
- Recent run history: successes, failures, timeouts, durations
- Signals it emitted recently and whether they look genuinely actionable
- Scratchpad memory the fleet holds that relates to this scout
- Whether its scope, thresholds, and schedule look right – suggest tuning if not

Lead with a short verdict. If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list, runs list, run emissions, scratchpad search).`
}
