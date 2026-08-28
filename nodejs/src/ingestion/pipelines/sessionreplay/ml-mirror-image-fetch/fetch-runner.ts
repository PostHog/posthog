import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'

import { FetchCandidate, MAX_HOPS, RepublishReason } from './collected-urls-record'
import {
    ConfigurationPolicyPass,
    ConfigurationPolicyService,
    explicitFreshnessLifetimeMs,
} from './configuration-policy'
import { ConfigurationCacheItem, CrawlHistoryItem, HttpCacheMetadata, UrlCrawlHistoryItem } from './crawl-history'
import { FetchCandidateLease, FetchCandidateQueue } from './fetch-candidate-queue'
import { FrontierPublisher, RepublishBatch, RepublishResult } from './frontier-publisher'
import { HostBudget } from './host-budget'
import {
    FetchOutcome,
    FetchRefusalReason,
    ImageFetcher,
    RequestScheduleBlockReason,
    TransientFetchOutcome,
} from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'
import { OriginRequestScheduler } from './origin-request-scheduler'
import { canonicalizeUrl } from './politeness-key'

export type ShedReason =
    | 'breaker_open'
    | 'backoff'
    | 'deadline'
    | 'connection_limit'
    | 'origin_map_full'
    | 'registrable_domain_map_full'
export const HOPS_EXHAUSTED = 'hops_exhausted'
export const DELAY_TOO_LONG = 'delay_too_long'
export type AttemptOutcome =
    | FetchOutcome
    | FetchRefusalReason
    | ShedReason
    | 'publish_failed'
    | typeof HOPS_EXHAUSTED
    | typeof DELAY_TOO_LONG

export interface FetchAttempt {
    candidate: FetchCandidate
    outcome: AttemptOutcome
    finished: boolean
    lost: boolean
    history?: UrlCrawlHistoryItem
    configurationUpdates: ConfigurationCacheItem[]
}

export interface FetchRunnerOptions {
    maxConcurrentPerRegistrableDomain: number
    maxInFlightRequests: number
    batchBudgetMs: number
    maxBytes: number
    requestTimeoutMs: number
    maxRedirects: number
    seenTtlSeconds: number
}

const TRANSIENT_OUTCOMES = new Set<TransientFetchOutcome>(['timeout', 'error', 'rate_limited', 'server_error'])
const ONE_MINUTE_MS = 60_000
const CONFIGURATION_RETRY_MS = 60 * 60 * 1000

function requirePositive(name: string, value: number): void {
    if (!Number.isFinite(value) || value <= 0) {
        throw new Error(`${name} must be a positive number, got ${value}`)
    }
}

function requirePositiveSafeInteger(name: string, value: number): void {
    if (!Number.isSafeInteger(value) || value <= 0) {
        throw new Error(`${name} must be a positive safe integer, got ${value}`)
    }
}

export function isTransientOutcome(outcome: AttemptOutcome): outcome is TransientFetchOutcome {
    return TRANSIENT_OUTCOMES.has(outcome as TransientFetchOutcome)
}

function isRequestStateFull(
    reason: string | undefined
): reason is Extract<RequestScheduleBlockReason, 'origin_map_full' | 'registrable_domain_map_full'> {
    return reason === 'origin_map_full' || reason === 'registrable_domain_map_full'
}

export interface FetchPass {
    run(
        candidates: FetchCandidate[],
        stored: Map<string, CrawlHistoryItem>,
        republishBatch?: RepublishBatch
    ): Promise<FetchAttempt[]>
}

interface FetchPassState {
    failure?: { error: unknown }
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
        requirePositiveSafeInteger(
            'SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_REGISTRABLE_DOMAIN',
            options.maxConcurrentPerRegistrableDomain
        )
        requirePositiveSafeInteger(
            'SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS',
            options.maxInFlightRequests
        )
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES', options.maxBytes)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS', options.requestTimeoutMs)
        requirePositive('AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS', options.seenTtlSeconds)
        if (!Number.isFinite(options.batchBudgetMs) || !Number.isFinite(options.maxRedirects)) {
            throw new Error('image fetch pass limits must be finite numbers')
        }
        this.candidateWork = new ConcurrencyController(options.maxInFlightRequests)
        ImageFetchRequestMetrics.trackBudget(budget, scheduler)
    }

    public async run(
        candidates: FetchCandidate[],
        stored: Map<string, CrawlHistoryItem>,
        republishBatch?: RepublishBatch
    ): Promise<FetchAttempt[]> {
        const activeRepublishBatch = republishBatch ?? this.publisher.createRepublishBatch()
        const deadlineMs = Date.now() + this.options.batchBudgetMs
        const configurationPolicy = this.configurationPolicy.createPass()
        const passState: FetchPassState = {}
        const configurationItems = new Map<string, ConfigurationCacheItem>()
        for (const [key, item] of stored) {
            if (item.kind === 'robots' || item.kind === 'tdmrep') {
                configurationItems.set(key, item)
            }
        }
        const queue = new FetchCandidateQueue(candidates, this.options)
        const podRequestSlots = Math.max(0, this.options.maxInFlightRequests - this.candidateWork.running)
        ImageFetchRequestMetrics.observeBatchSchedulableCapacity(
            Math.min(
                podRequestSlots,
                queue.availableRequestSlotsAtStart((registrableDomain) =>
                    this.budget.availableConnections(registrableDomain)
                )
            ),
            this.options.maxInFlightRequests
        )
        const attempts: FetchAttempt[] = []
        const workers = Array.from(
            { length: Math.min(this.options.maxInFlightRequests, queue.schedulableSlotsAtStart) },
            () =>
                this.runQueueWorker(
                    queue,
                    stored,
                    configurationItems,
                    configurationPolicy,
                    deadlineMs,
                    attempts,
                    activeRepublishBatch,
                    passState
                )
        )
        const settledWorkers = await Promise.allSettled(workers)
        if (passState.failure) {
            throw passState.failure.error
        }
        const failedWorker = settledWorkers.find(
            (settled): settled is PromiseRejectedResult => settled.status === 'rejected'
        )
        if (failedWorker) {
            throw failedWorker.reason
        }
        if (!republishBatch) {
            const result = await activeRepublishBatch.flush()
            if (result.failedUrls > 0) {
                throw new Error(`the image fetch lane could not account for ${result.failedUrls} URLs`)
            }
        }
        this.logFailures(attempts)
        return attempts
    }

    private async runQueueWorker(
        queue: FetchCandidateQueue,
        stored: Map<string, CrawlHistoryItem>,
        configurationItems: Map<string, ConfigurationCacheItem>,
        configurationPolicy: ConfigurationPolicyPass,
        deadlineMs: number,
        attempts: FetchAttempt[],
        republishBatch: RepublishBatch,
        passState: FetchPassState
    ): Promise<void> {
        for (;;) {
            const lease = queue.take()
            if (!lease) {
                return
            }
            try {
                attempts.push(
                    await this.processLease(
                        lease,
                        stored,
                        configurationItems,
                        configurationPolicy,
                        deadlineMs,
                        republishBatch,
                        passState
                    )
                )
            } catch (error) {
                passState.failure ??= { error }
                queue.abort()
                throw error
            } finally {
                lease.release()
            }
        }
    }

    private async processLease(
        lease: FetchCandidateLease,
        stored: Map<string, CrawlHistoryItem>,
        configurationItems: Map<string, ConfigurationCacheItem>,
        configurationPolicy: ConfigurationPolicyPass,
        deadlineMs: number,
        republishBatch: RepublishBatch,
        passState: FetchPassState
    ): Promise<FetchAttempt> {
        const candidate = lease.candidate
        if (candidate.remainingHops === 0) {
            return this.terminal(candidate, HOPS_EXHAUSTED, undefined, [])
        }
        if (Date.now() > deadlineMs) {
            return await this.republish(republishBatch, candidate, 'deadline', 'pass_deadline', 0, [])
        }
        return await this.candidateWork.run({
            debugTag: candidate.registrableDomain,
            fn: async () => {
                if (passState.failure) {
                    throw passState.failure.error
                }
                try {
                    if (Date.now() > deadlineMs) {
                        return await this.republish(republishBatch, candidate, 'deadline', 'pass_deadline', 0, [])
                    }
                    return await this.fetchOne(
                        candidate,
                        stored,
                        configurationItems,
                        configurationPolicy,
                        deadlineMs,
                        republishBatch
                    )
                } catch (error) {
                    passState.failure ??= { error }
                    throw error
                }
            },
        })
    }

    private async fetchOne(
        candidate: FetchCandidate,
        stored: Map<string, CrawlHistoryItem>,
        configurationItems: Map<string, ConfigurationCacheItem>,
        configurationPolicy: ConfigurationPolicyPass,
        deadlineMs: number,
        republishBatch: RepublishBatch
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
            ImageFetchRequestMetrics.observePolicyAndBudgetDecision(true, policy.reason ?? 'configuration_refused')
            if (policy.transient) {
                if (isRequestStateFull(policy.reason)) {
                    return await this.republish(
                        republishBatch,
                        candidate,
                        policy.reason,
                        policy.reason,
                        ONE_MINUTE_MS,
                        configurationUpdates
                    )
                }
                const waitMs = policy.reason === 'configuration_unreachable' ? CONFIGURATION_RETRY_MS : ONE_MINUTE_MS
                return await this.republish(
                    republishBatch,
                    candidate,
                    'backoff',
                    'not_ready',
                    waitMs,
                    configurationUpdates
                )
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
            ImageFetchRequestMetrics.observePolicyAndBudgetDecision(true, 'origin_map_full')
            return await this.republish(
                republishBatch,
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
            sourcePartitions: candidate.sourcePartitions,
            maxBytes: this.options.maxBytes,
            timeoutMs: this.options.requestTimeoutMs,
            maxRedirects: Math.min(this.options.maxRedirects, candidate.remainingHops),
            cache: previousUrl?.cache,
            tdmrepReservation: policy.tdmrepReservation,
            onRedirectResponse: () => this.budget.recordCompletedResponse(candidate.registrableDomain, Date.now()),
            isDifferentOrigin: (url) => url.origin !== candidate.origin,
            scheduleRequest: (url, requestDeadlineMs, request) =>
                this.scheduler.runImage(
                    url,
                    Math.min(deadlineMs, requestDeadlineMs),
                    request,
                    candidate.sourcePartitions
                ),
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
            registrableDomain: effectiveUrl.domain,
            remainingHops: candidate.remainingHops - result.redirects,
            fetchCount:
                candidate.fetchCount +
                result.redirects +
                (result.outcome === 'request_deferred' || result.outcome === 'redirect_policy_refused' ? 0 : 1),
        }

        if (result.outcome === 'redirect_policy_refused') {
            const reason = result.refusalReason ?? 'configuration_refused'
            ImageFetchRequestMetrics.observePolicyAndBudgetDecision(true, reason)
            if (result.policyTransient) {
                const stateFull = isRequestStateFull(reason)
                const republishReason: RepublishReason = stateFull ? reason : 'not_ready'
                const waitMs = reason === 'configuration_unreachable' ? CONFIGURATION_RETRY_MS : ONE_MINUTE_MS
                return await this.republish(
                    republishBatch,
                    attemptedCandidate,
                    reason,
                    republishReason,
                    waitMs,
                    configurationUpdates
                )
            }
            return this.terminal(attemptedCandidate, reason, undefined, configurationUpdates, reason)
        }

        if (result.outcome === 'request_deferred') {
            const reason = result.schedulingReason ?? 'deadline'
            ImageFetchRequestMetrics.observePolicyAndBudgetDecision(true, reason)
            const republishReason: RepublishReason = isRequestStateFull(reason)
                ? reason
                : reason === 'deadline' && Date.now() >= deadlineMs
                  ? 'pass_deadline'
                  : 'not_ready'
            const waitMs =
                republishReason === 'pass_deadline'
                    ? 0
                    : Math.max(
                          ONE_MINUTE_MS,
                          result.schedulingWaitMs ??
                              this.budget.blockedForMs(attemptedCandidate.registrableDomain, Date.now())
                      )
            return await this.republish(
                republishBatch,
                attemptedCandidate,
                reason,
                republishReason,
                waitMs,
                configurationUpdates
            )
        }

        ImageFetchRequestMetrics.observePolicyAndBudgetDecision(false)

        if (isTransientOutcome(result.outcome)) {
            const delayMs = this.budget.recordTransientFailure(
                candidate.registrableDomain,
                Date.now(),
                result.retryAfterMs
            )
            const attempt = await this.republish(
                republishBatch,
                attemptedCandidate,
                result.outcome,
                'retry',
                delayMs,
                configurationUpdates
            )
            return attempt
        }

        this.budget.recordCompletedResponse(candidate.registrableDomain, Date.now())
        if (
            (result.outcome === 'redirect_offsite' || result.outcome === 'redirect_continuation') &&
            result.redirectTarget
        ) {
            const canonical = canonicalizeUrl(result.redirectTarget.url)
            if (!canonical) {
                return this.terminal(attemptedCandidate, 'bad_redirect', result.cache, configurationUpdates)
            }
            return await this.republishToTarget(
                republishBatch,
                attemptedCandidate,
                result.outcome,
                {
                    currentUrl: canonical.fetch,
                    host: canonical.host,
                    origin: new URL(canonical.fetch).origin,
                    registrableDomain: canonical.domain,
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
        republishBatch: RepublishBatch,
        candidate: FetchCandidate,
        outcome: AttemptOutcome,
        reason: RepublishReason,
        waitMs: number,
        configurationUpdates: ConfigurationCacheItem[]
    ): Promise<FetchAttempt> {
        return await this.republishToTarget(
            republishBatch,
            candidate,
            outcome,
            {
                currentUrl: candidate.currentUrl,
                host: candidate.host,
                origin: candidate.origin,
                registrableDomain: candidate.registrableDomain,
            },
            reason,
            waitMs,
            configurationUpdates
        )
    }

    private async republishToTarget(
        republishBatch: RepublishBatch,
        candidate: FetchCandidate,
        outcome: AttemptOutcome,
        target: Pick<FetchCandidate, 'currentUrl' | 'host' | 'origin' | 'registrableDomain'>,
        reason: RepublishReason,
        waitMs: number,
        configurationUpdates: ConfigurationCacheItem[]
    ): Promise<FetchAttempt> {
        if ((reason === 'redirect' || reason === 'retry') && candidate.remainingHops <= 1) {
            return this.terminal(candidate, HOPS_EXHAUSTED, undefined, configurationUpdates)
        }
        const result: RepublishResult = await republishBatch.republish(candidate, target, reason, waitMs)
        if (result === 'refused_delay') {
            return this.terminal(candidate, DELAY_TOO_LONG, undefined, configurationUpdates)
        }
        return {
            candidate,
            outcome,
            finished: false,
            lost: false,
            configurationUpdates,
        }
    }

    private terminal(
        candidate: FetchCandidate,
        outcome: AttemptOutcome,
        cache: HttpCacheMetadata | undefined,
        configurationUpdates: ConfigurationCacheItem[],
        refusalReason: FetchRefusalReason | 'none' = 'none'
    ): FetchAttempt {
        const nowMs = Date.now()
        const minimumNextFetchAtMs = nowMs + this.options.seenTtlSeconds * 1000
        const explicitNextFetchAtMs = cache ? nowMs + explicitFreshnessLifetimeMs(cache, nowMs) : 0
        const nextFetchAtMs = Math.max(minimumNextFetchAtMs, explicitNextFetchAtMs)
        ImageFetchRequestMetrics.observeCompletedUrl(
            outcome,
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
