import type { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'

import type { FetchCandidate } from './collected-urls-record'
import { deduplicateFetchCandidates } from './fetch-candidate-queue'
import type { FetchAttempt } from './fetch-runner'
import type { SchedulerWaitScope } from './metrics'

const TOP_DOMAIN_FACTORS = 20
const MAX_TRACKED_DOMAIN_FACTORS = 2_000

type Recorder = { record(key: Record<string, string>, value: number): void }

export class ImageFetchTopHogMetrics {
    private readonly attempts: Recorder
    private readonly concurrencyLimitedUrls: Recorder
    private readonly schedulerWaitMs: Recorder

    constructor(topHog: TopHogRegistry) {
        this.attempts = topHog.registerSum('ml_image_fetch_attempts_by_registrable_domain', {
            topN: TOP_DOMAIN_FACTORS,
            maxKeys: MAX_TRACKED_DOMAIN_FACTORS,
        })
        this.concurrencyLimitedUrls = topHog.registerSum(
            'ml_image_fetch_concurrency_limited_urls_by_registrable_domain',
            {
                topN: TOP_DOMAIN_FACTORS,
                maxKeys: MAX_TRACKED_DOMAIN_FACTORS,
            }
        )
        this.schedulerWaitMs = topHog.registerSum('ml_image_fetch_scheduler_wait_ms_by_registrable_domain', {
            topN: TOP_DOMAIN_FACTORS,
            maxKeys: MAX_TRACKED_DOMAIN_FACTORS,
        })
    }

    public recordAttempt(attempt: FetchAttempt): void {
        this.attempts.record(
            {
                registrable_domain: attempt.candidate.registrableDomain,
                disposition: attempt.finished ? 'completed' : 'republished',
                outcome: attempt.outcome,
            },
            1
        )
    }

    public recordConcurrencyLimitedUrls(
        candidates: FetchCandidate[],
        concurrencyLimit: number,
        availableConnections: (registrableDomain: string) => number
    ): void {
        const candidateCounts = new Map<string, number>()
        for (const candidate of deduplicateFetchCandidates(candidates).candidates) {
            candidateCounts.set(
                candidate.registrableDomain,
                (candidateCounts.get(candidate.registrableDomain) ?? 0) + 1
            )
        }
        for (const [registrableDomain, candidateCount] of candidateCounts) {
            const limitedUrls = Math.max(0, candidateCount - availableConnections(registrableDomain))
            if (limitedUrls > 0) {
                this.concurrencyLimitedUrls.record(
                    {
                        registrable_domain: registrableDomain,
                        concurrency_limit: String(concurrencyLimit),
                    },
                    limitedUrls
                )
            }
        }
    }

    public recordSchedulerWait(registrableDomain: string, scope: SchedulerWaitScope, waitMs: number): void {
        if (waitMs <= 0) {
            return
        }
        this.schedulerWaitMs.record({ registrable_domain: registrableDomain, scope }, waitMs)
    }
}
