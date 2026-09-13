import type { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'

import type { ImageFetchBlockReason } from './block-reason'
import type { FetchCandidate } from './collected-urls-record'
import { deduplicateFetchCandidates } from './fetch-candidate-queue'
import type { FetchAttempt } from './fetch-runner'
import type { SchedulerWaitScope } from './metrics'

const TOP_DOMAIN_FACTORS = 20
const MAX_TRACKED_DOMAIN_FACTORS = 2_000

type Recorder = { record(key: Record<string, string>, value: number): void }

export class ImageFetchTopHogMetrics {
    private readonly attempts: Recorder
    private readonly blockEvents: Recorder
    private readonly blockedMs: Recorder

    constructor(topHog: TopHogRegistry) {
        this.attempts = topHog.registerSum('ml_image_fetch_attempts_by_registrable_domain', {
            topN: TOP_DOMAIN_FACTORS,
            maxKeys: MAX_TRACKED_DOMAIN_FACTORS,
        })
        this.blockEvents = topHog.registerSum('ml_image_fetch_block_events_by_registrable_domain', {
            topN: TOP_DOMAIN_FACTORS,
            maxKeys: MAX_TRACKED_DOMAIN_FACTORS,
        })
        this.blockedMs = topHog.registerSum('ml_image_fetch_blocked_ms_by_registrable_domain', {
            topN: TOP_DOMAIN_FACTORS,
            maxKeys: MAX_TRACKED_DOMAIN_FACTORS,
        })
    }

    public recordAttempt(attempt: FetchAttempt): void {
        this.recordForSourcePartitions(
            this.attempts,
            attempt.candidate.sourcePartitions,
            {
                registrable_domain: attempt.candidate.registrableDomain,
                disposition: attempt.finished ? 'completed' : 'republished',
                outcome: attempt.outcome,
            },
            1
        )
        if (attempt.block) {
            this.recordBlock(
                attempt.candidate.registrableDomain,
                attempt.candidate.sourcePartitions,
                attempt.block.reason,
                1,
                attempt.block.waitMs
            )
        }
    }

    public recordConcurrencyLimitedUrls(
        candidates: FetchCandidate[],
        availableConnections: (registrableDomain: string) => number
    ): void {
        const candidatesByRegistrableDomain = new Map<
            string,
            { candidateCount: number; sourcePartitions: Set<number> }
        >()
        for (const candidate of deduplicateFetchCandidates(candidates).candidates) {
            const domainCandidates = candidatesByRegistrableDomain.get(candidate.registrableDomain) ?? {
                candidateCount: 0,
                sourcePartitions: new Set<number>(),
            }
            domainCandidates.candidateCount += 1
            for (const sourcePartition of candidate.sourcePartitions ?? []) {
                domainCandidates.sourcePartitions.add(sourcePartition)
            }
            candidatesByRegistrableDomain.set(candidate.registrableDomain, domainCandidates)
        }
        for (const [registrableDomain, domainCandidates] of candidatesByRegistrableDomain) {
            const limitedUrls = Math.max(0, domainCandidates.candidateCount - availableConnections(registrableDomain))
            if (limitedUrls > 0) {
                this.recordBlock(
                    registrableDomain,
                    [...domainCandidates.sourcePartitions],
                    'domain_concurrency',
                    limitedUrls,
                    0
                )
            }
        }
    }

    public recordSchedulerWait(
        registrableDomain: string,
        sourcePartitions: readonly number[] | undefined,
        scope: SchedulerWaitScope,
        waitMs: number
    ): void {
        if (waitMs <= 0) {
            return
        }
        this.recordBlock(registrableDomain, sourcePartitions, scope, 1, waitMs)
    }

    private recordBlock(
        registrableDomain: string,
        sourcePartitions: readonly number[] | undefined,
        reason: ImageFetchBlockReason,
        eventCount: number,
        waitMs: number
    ): void {
        const key = { registrable_domain: registrableDomain, reason }
        this.recordForSourcePartitions(this.blockEvents, sourcePartitions, key, eventCount)
        if (waitMs > 0) {
            this.recordForSourcePartitions(this.blockedMs, sourcePartitions, key, waitMs)
        }
    }

    private recordForSourcePartitions(
        recorder: Recorder,
        sourcePartitions: readonly number[] | undefined,
        key: Record<string, string>,
        value: number
    ): void {
        const partitions = sourcePartitions?.length ? new Set(sourcePartitions) : new Set(['unattributed'])
        for (const partition of partitions) {
            recorder.record({ ...key, partition: String(partition) }, value)
        }
    }
}
