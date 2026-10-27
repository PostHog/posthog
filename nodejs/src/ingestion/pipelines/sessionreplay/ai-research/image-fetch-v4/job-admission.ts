import pLimit from 'p-limit'
import { Counter } from 'prom-client'

import {
    type TeamMonthKey,
    type TeamMonthKeys,
    teamMonthKeyExpiresAtMs,
    untilAborted,
} from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-month-keys'

import type { FetchCandidate } from './collected-urls-record'
import { parseV4UrlRef } from './v4-url-ref'

/** Each lookup's read budget starts when it starts, so a batch of many new team months must not start them all at once. */
const KEY_LOOKUP_CONCURRENCY = 16
/**
 * Bounds all key lookups of one batch together, so a batch of many new team months still leaves the fetch, history and
 * republish phases their time inside the consumer's 240s batch timeout.
 */
export const DEFAULT_KEY_BUDGET_MS = 60_000
/** A job whose key was not read in time waits in the first delay tier, so it does not come straight back to a busy key store. */
const DEFERRED_JOB_DELAY_MS = 60_000

const droppedJobs = new Counter({
    name: 'ai_research_v4_image_fetch_dropped_jobs_total',
    help: 'v4 fetch jobs dropped before any request, by reason.',
    labelNames: ['reason'],
})

const deferredJobs = new Counter({
    name: 'ai_research_v4_image_fetch_deferred_jobs_total',
    help: 'v4 fetch jobs sent to a delay tier because their team month key was not read within the batch key budget.',
})

const DEFERRED = Symbol('deferred')

/**
 * Drops a v4 job before any request when nothing could store its image: its team month has no live key, because the
 * key row expired, is missing or is a tombstone. The recorder stores the row before it sends a URL, so a missing row
 * means it expired.
 */
export class V4JobAdmission {
    private readonly keyLookups = pLimit(KEY_LOOKUP_CONCURRENCY)

    constructor(
        private readonly keys: Pick<TeamMonthKeys, 'get'>,
        private readonly keyBudgetMs = DEFAULT_KEY_BUDGET_MS
    ) {
        if (!Number.isSafeInteger(keyBudgetMs) || keyBudgetMs <= 0 || keyBudgetMs > 120_000) {
            throw new Error(
                `AI_RESEARCH_V4_IMAGE_FETCH_KEY_BUDGET_MS must be a whole number in (0, 120000], got ${keyBudgetMs}`
            )
        }
    }

    /**
     * Resolves to the jobs to fetch. A job whose key was not read within the budget stays in the batch with a later
     * `notBeforeMs`, so the consumer sends it to a delay tier, as the fetch pass does with a job its deadline passed.
     * A key read that fails before the budget runs out still fails the batch.
     */
    public async admit(candidates: FetchCandidate[], nowMs: number): Promise<FetchCandidate[]> {
        const budget = new AbortController()
        const timer = setTimeout(() => budget.abort(new Error('the v4 key admission budget ran out')), this.keyBudgetMs)
        try {
            return await this.admitWithin(candidates, nowMs, budget.signal)
        } finally {
            clearTimeout(timer)
            // Stops the lookups this batch still waits on when one of them failed.
            budget.abort()
        }
    }

    private async admitWithin(
        candidates: FetchCandidate[],
        nowMs: number,
        budget: AbortSignal
    ): Promise<FetchCandidate[]> {
        const keys = new Map<string, Promise<TeamMonthKey | typeof DEFERRED>>()
        const live: { candidate: FetchCandidate; teamMonth: string }[] = []
        for (const candidate of candidates) {
            const ref = parseV4UrlRef(candidate.originalRef)
            if (!ref) {
                droppedJobs.labels('foreign_ref').inc()
                continue
            }
            // DynamoDB removes an expired row some time after `expires_at`, so the row may still be there.
            if (teamMonthKeyExpiresAtMs(ref.keyMonth) <= nowMs) {
                droppedJobs.labels('expired').inc()
                continue
            }
            const teamMonth = `${ref.teamId}:${ref.keyMonth}`
            if (!keys.has(teamMonth)) {
                keys.set(
                    teamMonth,
                    this.lookUp(budget, () => this.keys.get(ref.teamId, ref.keyMonth, budget))
                )
            }
            live.push({ candidate, teamMonth })
        }
        const resolved = new Map(
            await Promise.all([...keys].map(async ([teamMonth, key]) => [teamMonth, await key] as const))
        )
        const admitted: FetchCandidate[] = []
        let deferred = 0
        for (const { candidate, teamMonth } of live) {
            const key = resolved.get(teamMonth)!
            if (key === DEFERRED) {
                deferred++
                admitted.push({
                    ...candidate,
                    notBeforeMs: Math.max(candidate.notBeforeMs, nowMs + DEFERRED_JOB_DELAY_MS),
                    lastBlockReason: 'pass_deadline',
                })
            } else if (key.status === 'ok') {
                admitted.push(candidate)
            } else {
                droppedJobs.labels(key.status === 'deleted' ? 'deleted' : 'missing_key').inc()
            }
        }
        if (deferred > 0) {
            deferredJobs.inc(deferred)
        }
        return admitted
    }

    private async lookUp(
        budget: AbortSignal,
        get: () => Promise<TeamMonthKey>
    ): Promise<TeamMonthKey | typeof DEFERRED> {
        try {
            return await untilAborted(
                this.keyLookups(() => {
                    budget.throwIfAborted()
                    return get()
                }),
                budget
            )
        } catch (error) {
            if (budget.aborted) {
                return DEFERRED
            }
            throw error
        }
    }
}
