import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'

import { FetchCandidate, MAX_HOPS, RepublishReason } from './collected-urls-record'
import {
    ConfigurationPolicyPass,
    ConfigurationPolicyService,
    explicitFreshnessLifetimeMs,
} from './configuration-policy'
import { ConfigurationCacheItem, CrawlHistoryItem, HttpCacheMetadata, UrlCrawlHistoryItem } from './crawl-history'
import { FrontierPublisher, RepublishResult } from './frontier-publisher'
import { HostBudget } from './host-budget'
import { FetchOutcome, ImageFetcher } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'
import { OriginRequestScheduler } from './origin-request-scheduler'
import { canonicalizeUrl } from './politeness-key'

export type ShedReason = 'breaker_open' | 'backoff' | 'deadline' | 'connection_limit' | 'origin_map_full'
export const HOPS_EXHAUSTED = 'hops_exhausted'
export const DELAY_TOO_LONG = 'delay_too_long'
export type AttemptOutcome = FetchOutcome | ShedReason | typeof HOPS_EXHAUSTED | typeof DELAY_TOO_LONG | string

export interface FetchAttempt {
    candidate: FetchCandidate
    outcome: AttemptOutcome
    finished: boolean
    lost: boolean
    history?: UrlCrawlHistoryItem
    configurationUpdates: ConfigurationCacheItem[]
}

export interface FetchRunnerOptions {
    maxConcurrentPerDomain: number
    maxInFlightRequests: number
    batchBudgetMs: number
    maxBytes: number
    requestTimeoutMs: number
    maxRedirects: number
    seenTtlSeconds: number
}

const TRANSIENT_OUTCOMES = new Set<FetchOutcome>(['timeout', 'error', 'rate_limited', 'server_error'])
const ONE_MINUTE_MS = 60_000
const CONFIGURATION_RETRY_MS = 60 * 60 * 1000

function requirePositive(name: string, value: number): void {
    if (!Number.isFinite(value) || value <= 0) {
        throw new Error(`${name} must be a positive number, got ${value}`)
    }
}

export interface FetchPass {
    run(candidates: FetchCandidate[], stored: Map<string, CrawlHistoryItem>): Promise<FetchAttempt[]>
}

export class FetchRunner implements FetchPass {
    private readonly candidateWork: ConcurrencyController

    constructor(
        private readonly fetcher: ImageFetcher,
        private readonly budget: HostBudget,
        private readonly scheduler: OriginRequestScheduler,
        private readonly configurationPolicy: ConfigurationPolicyService,
        private readonly options: FetchRunnerOptions,
        private readonly publisher: FrontierPublisher
    ) {
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_ORIGIN', options.maxConcurrentPerDomain)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS', options.maxInFlightRequests)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES', options.maxBytes)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS', options.requestTimeoutMs)
        requirePositive('AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS', options.seenTtlSeconds)
        if (!Number.isFinite(options.batchBudgetMs) || !Number.isFinite(options.maxRedirects)) {
            throw new Error('image fetch pass limits must be finite numbers')
        }
        this.candidateWork = new ConcurrencyController(options.maxInFlightRequests)
        ImageFetchRequestMetrics.trackBudget(budget, scheduler)
    }

    public async run(candidates: FetchCandidate[], stored: Map<string, CrawlHistoryItem>): Promise<FetchAttempt[]> {
        const deadlineMs = Date.now() + this.options.batchBudgetMs
        const configurationPolicy = this.configurationPolicy.createPass()
        const configurationItems = new Map<string, ConfigurationCacheItem>()
        for (const [key, item] of stored) {
            if (item.kind === 'robots' || item.kind === 'tdmrep') {
                configurationItems.set(key, item)
            }
        }
        const byOrigin = new Map<string, FetchCandidate[]>()
        for (const candidate of candidates) {
            const queue = byOrigin.get(candidate.origin)
            if (queue) {
                queue.push(candidate)
            } else {
                byOrigin.set(candidate.origin, [candidate])
            }
        }
        const attempts: FetchAttempt[] = []
        const originRuns = [...byOrigin].map(([origin, queue]) =>
            this.runOriginQueue(origin, queue, stored, configurationItems, configurationPolicy, deadlineMs, attempts)
        )
        const settledOrigins = await Promise.allSettled(originRuns)
        const failedOrigin = settledOrigins.find(
            (settled): settled is PromiseRejectedResult => settled.status === 'rejected'
        )
        if (failedOrigin) {
            throw failedOrigin.reason
        }
        this.logFailures(attempts)
        return attempts
    }

    private async runOriginQueue(
        origin: string,
        queue: FetchCandidate[],
        stored: Map<string, CrawlHistoryItem>,
        configurationItems: Map<string, ConfigurationCacheItem>,
        configurationPolicy: ConfigurationPolicyPass,
        deadlineMs: number,
        attempts: FetchAttempt[]
    ): Promise<void> {
        let next = 0
        const worker = async (): Promise<void> => {
            while (next < queue.length) {
                const candidate = queue[next++]
                if (candidate.remainingHops === 0) {
                    attempts.push(this.terminal(candidate, HOPS_EXHAUSTED, undefined, []))
                    continue
                }
                if (Date.now() > deadlineMs) {
                    attempts.push(await this.republish(candidate, 'deadline', 'pass_deadline', ONE_MINUTE_MS, []))
                    continue
                }
                attempts.push(
                    await this.candidateWork.run({
                        debugTag: origin,
                        fn: () => {
                            if (Date.now() > deadlineMs) {
                                return this.republish(candidate, 'deadline', 'pass_deadline', ONE_MINUTE_MS, [])
                            }
                            return this.fetchOne(candidate, stored, configurationItems, configurationPolicy, deadlineMs)
                        },
                    })
                )
            }
        }
        const settledWorkers = await Promise.allSettled(
            Array.from({ length: Math.min(this.options.maxConcurrentPerDomain, queue.length) }, worker)
        )
        const failedWorker = settledWorkers.find(
            (settled): settled is PromiseRejectedResult => settled.status === 'rejected'
        )
        if (failedWorker) {
            throw failedWorker.reason
        }
        void origin
    }

    private async fetchOne(
        candidate: FetchCandidate,
        stored: Map<string, CrawlHistoryItem>,
        configurationItems: Map<string, ConfigurationCacheItem>,
        configurationPolicy: ConfigurationPolicyPass,
        deadlineMs: number
    ): Promise<FetchAttempt> {
        if (candidate.remainingHops === 0) {
            return this.terminal(candidate, HOPS_EXHAUSTED, undefined, [])
        }
        const policy = await configurationPolicy.check(candidate.currentUrl, configurationItems, Date.now())
        const configurationUpdates = [...policy.updates]
        for (const update of policy.updates) {
            configurationItems.set(update.key, update)
        }
        if (!policy.allowed) {
            ImageFetchRequestMetrics.observeOriginStatus(true, policy.reason ?? 'configuration_refused')
            if (policy.transient) {
                const reason = policy.reason === 'origin_map_full' ? 'origin_map_full' : 'backoff'
                const republishReason: RepublishReason = reason === 'origin_map_full' ? 'origin_map_full' : 'not_ready'
                const waitMs = reason === 'origin_map_full' ? ONE_MINUTE_MS : CONFIGURATION_RETRY_MS
                return await this.republish(candidate, reason, republishReason, waitMs, configurationUpdates)
            }
            return this.terminal(
                candidate,
                policy.reason ?? 'configuration_refused',
                undefined,
                configurationUpdates,
                policy.reason ?? 'configuration_refused'
            )
        }
        if (!this.budget.setCrawlDelay(candidate.origin, policy.crawlDelayMs, Date.now())) {
            ImageFetchRequestMetrics.observeOriginStatus(true, 'origin_map_full')
            return await this.republish(
                candidate,
                'origin_map_full',
                'origin_map_full',
                ONE_MINUTE_MS,
                configurationUpdates
            )
        }

        const previous = stored.get(candidate.originalRef)
        const previousUrl = previous?.kind === 'url' ? previous : undefined
        const result = await this.fetcher.fetch(candidate.currentUrl, {
            maxBytes: this.options.maxBytes,
            timeoutMs: this.options.requestTimeoutMs,
            maxRedirects: Math.min(this.options.maxRedirects, candidate.remainingHops),
            cache: previousUrl?.cache,
            tdmrepReservation: policy.tdmrepReservation,
            onRedirectResponse: () => this.budget.recordCompletedResponse(candidate.origin, Date.now()),
            isOffsite: (url) => url.origin !== candidate.origin,
            scheduleRequest: (origin, requestDeadlineMs, request) =>
                this.scheduler.runImage(origin, Math.min(deadlineMs, requestDeadlineMs), request),
            checkRedirectPolicy: async (url) => {
                const redirectPolicy = await configurationPolicy.check(url, configurationItems, Date.now())
                for (const update of redirectPolicy.updates) {
                    configurationItems.set(update.key, update)
                    configurationUpdates.push(update)
                }
                if (!redirectPolicy.allowed) {
                    return {
                        allowed: false,
                        transient: redirectPolicy.transient,
                        reason: redirectPolicy.reason ?? 'configuration_refused',
                    }
                }
                const origin = new URL(url).origin
                if (!this.budget.setCrawlDelay(origin, redirectPolicy.crawlDelayMs, Date.now())) {
                    return { allowed: false, transient: true, reason: 'origin_map_full' }
                }
                return { allowed: true, tdmrepReservation: redirectPolicy.tdmrepReservation }
            },
        })
        ImageFetchRequestMetrics.observeRedirectCount(result.redirects)
        if (result.bytes) {
            ImageFetchRequestMetrics.observeBytes(result.bytes.length)
        }

        const effectiveUrl = canonicalizeUrl(result.currentUrl)
        if (!effectiveUrl) {
            return this.terminal(candidate, 'bad_redirect', result.cache, configurationUpdates)
        }
        const attemptedCandidate: FetchCandidate = {
            ...candidate,
            currentUrl: effectiveUrl.fetch,
            host: effectiveUrl.host,
            origin: new URL(effectiveUrl.fetch).origin,
            domain: effectiveUrl.domain,
            remainingHops: candidate.remainingHops - result.redirects,
            fetchCount:
                candidate.fetchCount +
                result.redirects +
                (result.outcome === 'request_deferred' || result.outcome === 'redirect_policy_refused' ? 0 : 1),
        }

        if (result.outcome === 'redirect_policy_refused') {
            const reason = result.refusalReason ?? 'configuration_refused'
            ImageFetchRequestMetrics.observeOriginStatus(true, reason)
            if (result.policyTransient) {
                const republishReason: RepublishReason = reason === 'origin_map_full' ? 'origin_map_full' : 'not_ready'
                const waitMs = reason === 'origin_map_full' ? ONE_MINUTE_MS : CONFIGURATION_RETRY_MS
                return await this.republish(attemptedCandidate, reason, republishReason, waitMs, configurationUpdates)
            }
            return this.terminal(attemptedCandidate, reason, undefined, configurationUpdates, reason)
        }

        if (result.outcome === 'request_deferred') {
            const reason = result.schedulingReason ?? 'deadline'
            ImageFetchRequestMetrics.observeOriginStatus(true, reason)
            const republishReason: RepublishReason =
                reason === 'origin_map_full'
                    ? 'origin_map_full'
                    : reason === 'deadline' && Date.now() >= deadlineMs
                      ? 'pass_deadline'
                      : 'not_ready'
            const waitMs = Math.max(
                ONE_MINUTE_MS,
                result.schedulingWaitMs ?? this.budget.blockedForMs(attemptedCandidate.origin, Date.now())
            )
            return await this.republish(attemptedCandidate, reason, republishReason, waitMs, configurationUpdates)
        }

        ImageFetchRequestMetrics.observeOriginStatus(false)

        if (TRANSIENT_OUTCOMES.has(result.outcome)) {
            const delayMs = this.budget.recordTransientFailure(candidate.origin, Date.now(), result.retryAfterMs)
            return await this.republish(attemptedCandidate, result.outcome, 'retry', delayMs, configurationUpdates)
        }

        this.budget.recordCompletedResponse(candidate.origin, Date.now())
        if (
            (result.outcome === 'redirect_offsite' || result.outcome === 'redirect_continuation') &&
            result.redirectTarget
        ) {
            const canonical = canonicalizeUrl(result.redirectTarget.url)
            if (!canonical) {
                return this.terminal(attemptedCandidate, 'bad_redirect', result.cache, configurationUpdates)
            }
            return await this.republishToTarget(
                attemptedCandidate,
                result.outcome,
                {
                    currentUrl: canonical.fetch,
                    host: canonical.host,
                    origin: new URL(canonical.fetch).origin,
                    domain: canonical.domain,
                },
                'redirect',
                0,
                configurationUpdates
            )
        }
        if (result.outcome === 'ok') {
            try {
                await this.publisher.publishImage(attemptedCandidate, result)
            } catch {
                return {
                    candidate: attemptedCandidate,
                    outcome: 'publish_failed',
                    finished: false,
                    lost: true,
                    configurationUpdates,
                }
            }
        }
        const responseCache = result.redirects > 0 ? withoutValidators(result.cache) : result.cache
        const mergedCache =
            result.outcome === 'not_modified' ? mergeCache(previousUrl?.cache, responseCache) : responseCache
        return this.terminal(
            attemptedCandidate,
            result.outcome,
            mergedCache,
            configurationUpdates,
            result.refusalReason
        )
    }

    private async republish(
        candidate: FetchCandidate,
        outcome: AttemptOutcome,
        reason: RepublishReason,
        waitMs: number,
        configurationUpdates: ConfigurationCacheItem[]
    ): Promise<FetchAttempt> {
        return await this.republishToTarget(
            candidate,
            outcome,
            {
                currentUrl: candidate.currentUrl,
                host: candidate.host,
                origin: candidate.origin,
                domain: candidate.domain,
            },
            reason,
            waitMs,
            configurationUpdates
        )
    }

    private async republishToTarget(
        candidate: FetchCandidate,
        outcome: AttemptOutcome,
        target: Pick<FetchCandidate, 'currentUrl' | 'host' | 'origin' | 'domain'>,
        reason: RepublishReason,
        waitMs: number,
        configurationUpdates: ConfigurationCacheItem[]
    ): Promise<FetchAttempt> {
        if ((reason === 'redirect' || reason === 'retry') && candidate.remainingHops <= 1) {
            return this.terminal(candidate, HOPS_EXHAUSTED, undefined, configurationUpdates)
        }
        const result: RepublishResult = await this.publisher.republish(candidate, target, reason, waitMs)
        if (result === 'refused_delay') {
            return this.terminal(candidate, DELAY_TOO_LONG, undefined, configurationUpdates)
        }
        return {
            candidate,
            outcome,
            finished: false,
            lost: result === 'failed',
            configurationUpdates,
        }
    }

    private terminal(
        candidate: FetchCandidate,
        outcome: AttemptOutcome,
        cache: HttpCacheMetadata | undefined,
        configurationUpdates: ConfigurationCacheItem[],
        refusalReason = 'none'
    ): FetchAttempt {
        const nowMs = Date.now()
        const minimumNextFetchAtMs = nowMs + this.options.seenTtlSeconds * 1000
        const explicitNextFetchAtMs = cache ? nowMs + explicitFreshnessLifetimeMs(cache, nowMs) : 0
        const nextFetchAtMs = Math.max(minimumNextFetchAtMs, explicitNextFetchAtMs)
        ImageFetchRequestMetrics.observeCompletedUrl(
            String(outcome),
            refusalReason,
            Math.max(0, nowMs - candidate.firstSeenAtMs) / 1000,
            candidate.fetchCount,
            candidate.republishCount
        )
        ImageFetchRequestMetrics.observeHops(MAX_HOPS - candidate.remainingHops)
        return {
            candidate,
            outcome,
            finished: true,
            lost: false,
            history: {
                kind: 'url',
                key: candidate.originalRef,
                nextFetchAtMs,
                storageExpiresAtMs: nextFetchAtMs,
                outcome: String(outcome),
                cache,
            },
            configurationUpdates,
        }
    }

    private logFailures(attempts: FetchAttempt[]): void {
        const failures = attempts.filter((attempt) => attempt.outcome !== 'ok' && attempt.outcome !== 'not_modified')
        if (failures.length === 0) {
            return
        }
        logger.warn('🌐', 'ml_image_fetch_batch_failures', {
            count: failures.length,
            outcomes: [...new Set(failures.map((attempt) => String(attempt.outcome)))].slice(0, 10),
            hosts: [...new Set(failures.map((attempt) => attempt.candidate.host))].slice(0, 5),
        })
    }
}

function mergeCache(
    previous: HttpCacheMetadata | undefined,
    update: HttpCacheMetadata | undefined
): HttpCacheMetadata | undefined {
    if (!previous) {
        return update
    }
    if (!update) {
        return previous
    }
    const definedUpdate = Object.fromEntries(Object.entries(update).filter(([, value]) => value !== undefined))
    return { ...previous, ...definedUpdate }
}

function withoutValidators(cache: HttpCacheMetadata | undefined): HttpCacheMetadata | undefined {
    return cache ? { ...cache, etag: undefined, lastModified: undefined } : undefined
}
