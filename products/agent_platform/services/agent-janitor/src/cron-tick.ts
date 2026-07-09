/**
 * Periodic cron firing — `cronTick()` runs on the same 30s setInterval as
 * `sweepOnce`. Each tick:
 *
 *   1. Lists every application's live revision that declares at least one
 *      cron trigger.
 *   2. For each cron trigger on each such revision, asks `cron-parser` for
 *      every firing in `(lastTickAt, now]`.
 *   3. Applies the `catch_up` policy (`all` | `most_recent` | `skip`) bounded
 *      by `max_catch_up_age_seconds` to decide which firings survive.
 *   4. Renders the firing message + optional `external_key` with placeholder
 *      expansion (`{fired_at:iso}`, `{cron_name}`, etc.).
 *   5. Calls `enqueueOrResume()` with an idempotency key of the form
 *      `cron:<rev>:<name>:<fired_at_minute>` so a sibling janitor replica
 *      racing on the same firing collapses cleanly via the unique index
 *      added in PR-1.
 *
 * `lastTickAt` is per-process in memory. On janitor restart it resets to
 * `now`; the catch-up policy is what handles missed firings — there's no
 * persisted clock. The plan §6 calls this out as deliberate: the unique
 * index on `(application_id, idempotency_key)` is the load-bearing
 * "did we fire this minute" source of truth, not any in-memory state.
 */

import cronParser from 'cron-parser'

import { enqueueOrResume } from '@posthog/agent-ingress'
import {
    AgentApplication,
    AgentRevision,
    createLogger,
    RevisionStore,
    SessionPrincipal,
    SessionQueue,
} from '@posthog/agent-shared'

const log = createLogger('cron-tick')

export interface CronTickDeps {
    revisions: RevisionStore
    queue: SessionQueue
    /** Injectable clock for tests; defaults to `() => new Date()`. */
    now?: () => Date
    /**
     * Application loader. The revision store's `listLiveCronRevisions()`
     * returns revisions; we need the matching `AgentApplication` for each
     * to call `enqueueOrResume` (the team_id comes from the app, not
     * a global dep — different apps live on different teams).
     * Defaults to `revisions.getApplication(rev.application_id)`.
     */
    getApplication?: (applicationId: string) => Promise<AgentApplication | null>
}

export interface CronTickResult {
    fired: number
    skipped_no_window: number
    skipped_caught_up: number
    skipped_no_app: number
    errors: number
}

/**
 * Service principal stamped on every cron-fired session. Distinguishable
 * from human-driven principals at the strict-principal check + audit log.
 */
const CRON_PRINCIPAL: SessionPrincipal = { kind: 'service', id: 'cron' }

/**
 * Hard cap on firings fired for a single cron trigger in one tick. Only bites
 * `catch_up: "all"` (`most_recent` / `skip` yield <=1). A runtime backstop for
 * specs that predate the freeze-time frequency guard or that fire
 * legitimately-often after a long pause; truncation is logged, never silent.
 */
const MAX_FIRINGS_PER_TICK = 100

/**
 * One firing per `cronTick()` invocation, per cron trigger, per surviving
 * firing time within `(lastTickAt, now]`. Stateful across invocations: pass
 * the same `tickState` back in so `lastTickAt` advances.
 */
export interface CronTickState {
    lastTickAt: Date | null
}

export function newCronTickState(): CronTickState {
    return { lastTickAt: null }
}

/**
 * Fire one cron job out-of-band, bypassing the scheduler's window logic.
 * Used by the manual-fire endpoint (`POST /revisions/:id/cron/fire`) for
 * authoring — the user clicks "fire now" and gets the same execution path
 * a scheduled firing would walk. Dedupe key shape differs from the
 * scheduled path: `cron-manual:<rev>:<name>:<requestId>`, so a real
 * scheduled firing at the same minute doesn't collide.
 */
export async function fireCronManually(
    deps: CronTickDeps,
    input: {
        rev: AgentRevision
        app: AgentApplication
        cronName: string
        requestId: string
        firedAt?: Date
    }
): Promise<{ session_id: string; fired_at: string; idempotency_key: string }> {
    const trigger = input.rev.spec.triggers.find((t) => t.type === 'cron' && t.config.name === input.cronName)
    if (!trigger || trigger.type !== 'cron') {
        throw new Error(`unknown_cron:${input.cronName}`)
    }
    const firedAt = input.firedAt ?? (deps.now ?? (() => new Date()))()
    const renderedPrompt = expandPlaceholders(trigger.config.prompt, trigger.config, firedAt)
    const renderedExternalKey = trigger.config.external_key
        ? expandPlaceholders(trigger.config.external_key, trigger.config, firedAt)
        : null

    const triggerMetadata = {
        kind: 'cron' as const,
        cron_name: trigger.config.name,
        schedule: trigger.config.schedule,
        fired_at: firedAt.toISOString(),
        manual: true,
    }
    const idempotencyKey = `cron-manual:${input.rev.id}:${trigger.config.name}:${input.requestId}`

    const outcome = await enqueueOrResume(
        { queue: deps.queue },
        {
            application: input.app,
            revision: input.rev,
            externalKey: renderedExternalKey,
            idempotencyKey,
            triggerMetadata,
            seed: {
                role: 'user',
                content: renderedPrompt,
                timestamp: firedAt.getTime(),
                sender: CRON_PRINCIPAL,
            },
            principal: CRON_PRINCIPAL,
            trigger: 'webhook',
        }
    )
    return {
        session_id: outcome.sessionId,
        fired_at: firedAt.toISOString(),
        idempotency_key: idempotencyKey,
    }
}

export async function cronTick(deps: CronTickDeps, state: CronTickState): Promise<CronTickResult> {
    const now = (deps.now ?? (() => new Date()))()
    const lastTickAt = state.lastTickAt ?? now
    state.lastTickAt = now

    const result: CronTickResult = {
        fired: 0,
        skipped_no_window: 0,
        skipped_caught_up: 0,
        skipped_no_app: 0,
        errors: 0,
    }

    const revs = await deps.revisions.listLiveCronRevisions()
    if (revs.length === 0) {
        return result
    }

    const getApp = deps.getApplication ?? ((id: string) => deps.revisions.getApplication(id))

    for (const rev of revs) {
        const app = await getApp(rev.application_id)
        if (!app) {
            result.skipped_no_app++
            continue
        }
        for (const trigger of rev.spec.triggers) {
            if (trigger.type !== 'cron') {
                continue
            }
            const cfg = trigger.config
            // Clamp the enumeration window to `max_catch_up_age_seconds` BEFORE
            // walking — `applyCatchUp` would discard anything older, but
            // sub-minute schedules (cron-parser accepts 6-field `* * * * * *`)
            // turn a paused janitor + the 7-day cap into 604,800 wasted
            // iterations on a single tick. Cap the window first so we never
            // enumerate firings we'd throw away.
            const ageCapMs = cfg.max_catch_up_age_seconds * 1000
            const earliestAllowed = new Date(now.getTime() - ageCapMs)
            const windowFrom = lastTickAt > earliestAllowed ? lastTickAt : earliestAllowed
            let firings: Date[]
            try {
                firings = enumerateFirings(cfg.schedule, cfg.timezone, windowFrom, now)
            } catch (err) {
                log.warn(
                    {
                        revision_id: rev.id,
                        cron_name: cfg.name,
                        err: (err as Error).message,
                    },
                    'cron.tick.parse_failed'
                )
                result.errors++
                continue
            }
            if (firings.length === 0) {
                result.skipped_no_window++
                continue
            }
            let survivors = applyCatchUp(firings, cfg.catch_up, cfg.max_catch_up_age_seconds, now)
            result.skipped_caught_up += firings.length - survivors.length

            // Backstop the validation guard: only `catch_up: "all"` can yield
            // more than one survivor, and a long pause on a frequent schedule
            // can still pile up thousands. Keep the most recent firings, drop
            // the stale tail, and log it — never silently truncate.
            if (survivors.length > MAX_FIRINGS_PER_TICK) {
                const dropped = survivors.length - MAX_FIRINGS_PER_TICK
                survivors = survivors.slice(-MAX_FIRINGS_PER_TICK)
                result.skipped_caught_up += dropped
                log.warn(
                    {
                        revision_id: rev.id,
                        cron_name: cfg.name,
                        dropped,
                        kept: MAX_FIRINGS_PER_TICK,
                    },
                    'cron.tick.firings_capped'
                )
            }

            for (const firedAt of survivors) {
                try {
                    await fireOne(deps, rev, app, cfg, firedAt)
                    result.fired++
                } catch (err) {
                    log.error(
                        {
                            revision_id: rev.id,
                            cron_name: cfg.name,
                            fired_at: firedAt.toISOString(),
                            err: (err as Error).message,
                        },
                        'cron.tick.fire_failed'
                    )
                    result.errors++
                }
            }
        }
    }

    return result
}

interface CronConfig {
    name: string
    schedule: string
    timezone: string
    prompt: string
    external_key?: string
    catch_up: 'all' | 'most_recent' | 'skip'
    max_catch_up_age_seconds: number
}

async function fireOne(
    deps: CronTickDeps,
    rev: AgentRevision,
    app: AgentApplication,
    cfg: CronConfig,
    firedAt: Date
): Promise<void> {
    const renderedPrompt = expandPlaceholders(cfg.prompt, cfg, firedAt)
    const renderedExternalKey = cfg.external_key ? expandPlaceholders(cfg.external_key, cfg, firedAt) : null

    const triggerMetadata = {
        kind: 'cron' as const,
        cron_name: cfg.name,
        schedule: cfg.schedule,
        fired_at: firedAt.toISOString(),
    }

    // Minute-rounded so two janitor replicas firing at slightly different
    // wall-clock times for the same scheduled minute still collide on the
    // unique index. cron-parser emits `Date` objects pinned to the scheduled
    // moment — truncating to the minute preserves identity across replicas.
    const firedAtMinute = Math.floor(firedAt.getTime() / 60_000)
    const idempotencyKey = `cron:${rev.id}:${cfg.name}:${firedAtMinute}`

    await enqueueOrResume(
        { queue: deps.queue },
        {
            application: app,
            revision: rev,
            externalKey: renderedExternalKey,
            idempotencyKey,
            triggerMetadata,
            seed: {
                role: 'user',
                content: renderedPrompt,
                timestamp: firedAt.getTime(),
                sender: CRON_PRINCIPAL,
            },
            principal: CRON_PRINCIPAL,
            trigger: 'webhook',
        }
    )
}

/**
 * Yield every firing time from `cron-parser` strictly after `from` and at or
 * before `to`. Returns in ascending order.
 */
function enumerateFirings(schedule: string, timezone: string, from: Date, to: Date): Date[] {
    const it = cronParser.parseExpression(schedule, {
        currentDate: new Date(from.getTime() + 1), // strictly after — cron-parser includes `currentDate`
        endDate: to,
        tz: timezone,
    })
    const out: Date[] = []
    while (true) {
        let next: ReturnType<typeof it.next>
        try {
            next = it.next()
        } catch {
            // cron-parser throws when iteration runs past endDate.
            break
        }
        const ts = next.toDate()
        if (ts.getTime() > to.getTime()) {
            break
        }
        out.push(ts)
    }
    return out
}

/**
 * Apply the catch-up policy to a sorted-ascending list of firings within the
 * window. Plan §7:
 *   - `all` — fire every survivor within `max_catch_up_age_seconds`.
 *   - `most_recent` — fire only the latest survivor (default).
 *   - `skip` — drop everything older than `max_catch_up_age_seconds`.
 *     (Realistically the only firing that matters is the most recent; if
 *     it's outside the age window, drop it.)
 *
 * `max_catch_up_age_seconds` is a hard cap regardless of mode — a firing
 * older than the cap is always dropped.
 */
function applyCatchUp(firings: Date[], mode: 'all' | 'most_recent' | 'skip', maxAgeSeconds: number, now: Date): Date[] {
    const ageCap = now.getTime() - maxAgeSeconds * 1000
    const inAge = firings.filter((f) => f.getTime() >= ageCap)
    if (inAge.length === 0) {
        return []
    }
    if (mode === 'skip') {
        // `skip` fires only if the most recent firing IS the only firing —
        // there are no missed ones to skip. Otherwise drop the lot.
        return inAge.length === 1 ? inAge : []
    }
    if (mode === 'most_recent') {
        return [inAge[inAge.length - 1]]
    }
    // 'all'
    return inAge
}

/**
 * Replace `{placeholder}` tokens with their resolved values. Whitelist
 * matches `validate-spec.ts:CRON_PLACEHOLDERS`. Unknown placeholders pass
 * through unchanged — at this point in the flow the validator already
 * rejected them at freeze time, so the only way one reaches here is a spec
 * that bypassed validation (in tests).
 */
function expandPlaceholders(input: string, cfg: CronConfig, firedAt: Date): string {
    const iso = firedAt.toISOString()
    const date = iso.slice(0, 10)
    const week = isoWeek(firedAt)
    const replacements: Record<string, string> = {
        'fired_at:iso': iso,
        'fired_at:date': date,
        'fired_at:week': week,
        schedule: cfg.schedule,
        cron_name: cfg.name,
    }
    return input.replace(/\{([^{}\s]+)\}/g, (_match, key) => replacements[key] ?? `{${key}}`)
}

/**
 * ISO 8601 week date (`YYYY-Www`). Matches the format authors typically
 * want for "this week's digest" keys. Algorithm:
 *   W = floor((ordinal - dayOfWeek + 10) / 7)
 * where `ordinal` is day-of-year (1-indexed) and `dayOfWeek` is ISO
 * (Mon=1 ... Sun=7). Edge cases at the year boundary roll over to the
 * neighbouring year's last/first week per ISO 8601.
 */
function isoWeek(d: Date): string {
    const year = d.getUTCFullYear()
    const yearStart = Date.UTC(year, 0, 1)
    const ordinal = Math.floor((d.getTime() - yearStart) / 86_400_000) + 1
    const dayOfWeek = d.getUTCDay() || 7
    const w = Math.floor((ordinal - dayOfWeek + 10) / 7)
    if (w < 1) {
        const prev = year - 1
        return `${prev}-W${String(isoWeeksInYear(prev)).padStart(2, '0')}`
    }
    if (w > isoWeeksInYear(year)) {
        return `${year + 1}-W01`
    }
    return `${year}-W${String(w).padStart(2, '0')}`
}

/** Years where Jan 1 is Thursday or Dec 31 is Thursday have 53 ISO weeks. */
function isoWeeksInYear(year: number): number {
    const jan1Dow = new Date(Date.UTC(year, 0, 1)).getUTCDay()
    const dec31Dow = new Date(Date.UTC(year, 11, 31)).getUTCDay()
    return jan1Dow === 4 || dec31Dow === 4 ? 53 : 52
}
