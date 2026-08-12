import { logger } from '~/common/utils/logger'
import { delay } from '~/common/utils/utils'

import { FetchCandidate } from './collected-urls-record'
import { HostBudget } from './host-budget'
import { FetchOutcome, ImageFetchResult, ImageFetcher, RedirectDecision } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'
import { politenessKey } from './politeness-key'

/** Why a URL never reached a request. Shares `rate_limited` with the response of the same name, because both mean the site asked us to wait. */
export type ShedReason = 'breaker_open' | 'rate_limited' | 'deadline'

export type AttemptOutcome = FetchOutcome | ShedReason

export interface FetchAttempt {
    candidate: FetchCandidate
    outcome: AttemptOutcome
}

export interface FetchRunnerOptions {
    /** Connections this pod opens to one registrable domain at once. It is also the worker count, so nothing else has to enforce it. */
    maxConcurrentPerDomain: number
    /** Domains this pod fetches from at once. It bounds the whole pass, because a batch can carry one domain per record. */
    maxConcurrentDomains: number
    /** Wall time the whole pass may take. What it does not reach is shed and fetched again the next time a session refers to it. */
    batchBudgetMs: number
    maxBytes: number
    requestTimeoutMs: number
    maxRedirects: number
    /** Held for a 429 or a 503 that named no period, so a site that only says "slow down" still gets a pause. */
    defaultRetryAfterMs: number
}

/**
 * An outcome that says what this URL is, rather than what this moment is.
 *
 * Only these record a sighting. A URL shed by the budget, or lost to a timeout, is left unrecorded
 * so the next session that refers to it tries again. A sighting written for one of those would
 * suppress the URL for the whole sighting TTL because a site was busy for a moment.
 */
const TERMINAL_OUTCOMES: ReadonlySet<AttemptOutcome> = new Set<AttemptOutcome>([
    'ok',
    'not_found',
    'forbidden',
    'too_large',
    'not_image',
    'blocked',
    'bad_redirect',
    'too_many_redirects',
    'unexpected_status',
])

/** Hosts named in one batch-level log line. Enough to find the site, bounded so one bad batch cannot write a host list of its own size. */
const MAX_LOGGED_HOSTS = 5

/** A number from the environment, where a typo parses to NaN. Every one of these is a politeness control that a NaN would switch off. */
function requirePositive(name: string, value: number): number {
    if (!Number.isFinite(value) || value <= 0) {
        throw new Error(`${name} must be a positive number, got ${value}`)
    }
    return value
}

export function isTerminal(outcome: AttemptOutcome): boolean {
    return TERMINAL_OUTCOMES.has(outcome)
}

/** What the consumer needs of the fetch pass, so its tests exercise the real contract rather than a cast. */
export interface FetchPass {
    run(candidates: FetchCandidate[]): Promise<FetchAttempt[]>
}

/**
 * Runs the fetches of one poll batch inside the per-domain budget.
 *
 * Domains run in parallel and are independent: one slow site delays only its own URLs. Inside a
 * domain the worker count is the connection limit and the token bucket is the rate, so a domain
 * receives from this pod exactly what an operator configured for it.
 *
 * The pass is bounded by wall time rather than by work. A batch can hold more URLs for one domain
 * than a polite rate carries in the time a Kafka batch may take. The lane then does less work. It
 * does not send faster.
 */
export class FetchRunner implements FetchPass {
    constructor(
        private readonly fetcher: ImageFetcher,
        private readonly budget: HostBudget,
        private readonly options: FetchRunnerOptions
    ) {
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN', options.maxConcurrentPerDomain)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_DOMAINS', options.maxConcurrentDomains)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES', options.maxBytes)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS', options.requestTimeoutMs)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_DEFAULT_RETRY_AFTER_MS', options.defaultRetryAfterMs)
        // The batch budget and the redirect limit may be zero: no fetch at all, and no redirect at
        // all, are both meaningful settings. A NaN is not.
        if (!Number.isFinite(options.batchBudgetMs) || !Number.isFinite(options.maxRedirects)) {
            throw new Error('SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_BUDGET_MS and MAX_REDIRECTS must be numbers')
        }
    }

    public async run(candidates: FetchCandidate[]): Promise<FetchAttempt[]> {
        if (candidates.length === 0) {
            return []
        }
        const deadlineMs = Date.now() + this.options.batchBudgetMs
        const byDomain = new Map<string, FetchCandidate[]>()
        for (const candidate of candidates) {
            const queue = byDomain.get(candidate.domain)
            if (queue) {
                queue.push(candidate)
            } else {
                byDomain.set(candidate.domain, [candidate])
            }
        }

        const attempts = await this.runDomains([...byDomain], deadlineMs)
        ImageFetchRequestMetrics.observeBudget(
            this.budget.trackedDomains,
            this.budget.blockedDomains(Date.now()),
            this.budget.evictedWhileBlocked
        )
        this.logFailures(attempts)
        return attempts
    }

    /**
     * One line for the whole pass rather than one per URL.
     *
     * A batch can carry thousands of URLs, and a site that is down turns every one of them into a
     * log line. The counts answer the same question, and the hosts name where to look. The host,
     * never the URL: a URL is page content and belongs in no log.
     */
    private logFailures(attempts: FetchAttempt[]): void {
        const byOutcome = new Map<AttemptOutcome, { count: number; hosts: Set<string> }>()
        for (const attempt of attempts) {
            if (attempt.outcome === 'ok') {
                continue
            }
            const seen = byOutcome.get(attempt.outcome) ?? { count: 0, hosts: new Set<string>() }
            seen.count++
            if (seen.hosts.size < MAX_LOGGED_HOSTS) {
                seen.hosts.add(attempt.candidate.host)
            }
            byOutcome.set(attempt.outcome, seen)
        }
        for (const [outcome, seen] of byOutcome) {
            logger.warn('🌐', 'ml_image_fetch_batch_failures', {
                outcome,
                count: seen.count,
                hosts: [...seen.hosts],
            })
        }
    }

    /**
     * A pool rather than one promise per domain. One Kafka record carries one domain, so a full
     * batch offers as many domains as it has records, and an unbounded fan-out would open that many
     * budgets, sockets, and image buffers at once.
     *
     * A domain the pool does not reach before the deadline still runs. Its first request is refused
     * for the deadline, so it sheds its queue without sending.
     */
    private async runDomains(entries: [string, FetchCandidate[]][], deadlineMs: number): Promise<FetchAttempt[]> {
        const attempts: FetchAttempt[] = []
        let next = 0
        const worker = async (): Promise<void> => {
            while (next < entries.length) {
                const [domain, queue] = entries[next++]
                attempts.push(...(await this.runDomain(domain, queue, deadlineMs)))
            }
        }
        const workers = Math.min(this.options.maxConcurrentDomains, entries.length)
        await Promise.all(Array.from({ length: workers }, () => worker()))
        return attempts
    }

    private async runDomain(domain: string, queue: FetchCandidate[], deadlineMs: number): Promise<FetchAttempt[]> {
        const attempts: FetchAttempt[] = []
        let next = 0
        // A refusal is a property of the domain, so it applies to every URL still queued for it
        // rather than only to the one that asked.
        const shedRemaining = (reason: ShedReason): void => {
            while (next < queue.length) {
                attempts.push({ candidate: queue[next++], outcome: reason })
                ImageFetchRequestMetrics.incOutcome(reason)
            }
        }

        const worker = async (): Promise<void> => {
            while (next < queue.length) {
                const grant = this.budget.take(domain, Date.now(), deadlineMs)
                if (!grant.granted) {
                    shedRemaining(grant.reason)
                    return
                }
                const candidate = queue[next++]
                ImageFetchRequestMetrics.observeBudgetWait(grant.waitMs / 1000)
                if (grant.waitMs > 0) {
                    await delay(grant.waitMs)
                }
                attempts.push(await this.fetchOne(candidate, deadlineMs))
            }
        }

        const workers = Math.min(this.options.maxConcurrentPerDomain, queue.length)
        await Promise.all(Array.from({ length: workers }, () => worker()))
        return attempts
    }

    /**
     * The request gets its whole configured timeout even when the batch deadline is closer.
     *
     * A request cut short by the batch clock would time out through no fault of the site, and the
     * budget would read that as the site failing. So the deadline decides whether a request starts,
     * and never how long it may take. One pass can therefore run to `batchBudgetMs` plus one
     * request timeout, which is still far inside Kafka's max.poll.interval.ms.
     */
    private async fetchOne(candidate: FetchCandidate, deadlineMs: number): Promise<FetchAttempt> {
        const startedAt = process.hrtime.bigint()
        let result: ImageFetchResult
        try {
            result = await this.fetcher.fetch(candidate.url, {
                maxBytes: this.options.maxBytes,
                timeoutMs: this.options.requestTimeoutMs,
                maxRedirects: this.options.maxRedirects,
                authorizeRedirect: (url) => this.authorizeRedirect(url, deadlineMs),
            })
        } catch (error) {
            // The fetcher answers with an outcome rather than a throw, so reaching here means a
            // defect. It is caught anyway: a throw would leave the other domains of this batch
            // running while the partition replays them.
            logger.error('🌐', 'ml_image_fetch_unhandled_error', { host: candidate.host, error: String(error) })
            ImageFetchRequestMetrics.incOutcome('error')
            return { candidate, outcome: 'error' }
        }
        const durationSeconds = Number(process.hrtime.bigint() - startedAt) / 1e9

        this.applyToBudget(candidate.domain, result.outcome, result.retryAfterMs)
        ImageFetchRequestMetrics.observeRequest(result.outcome, durationSeconds, result.redirects)
        if (result.bytes) {
            ImageFetchRequestMetrics.observeBytes(result.bytes.length)
        }
        // The bytes stop here. Nothing produces them yet, and a batch of them held for a consumer
        // that does not exist is the largest memory this lane could hold.
        return { candidate, outcome: result.outcome }
    }

    private applyToBudget(domain: string, outcome: FetchOutcome, retryAfterMs: number | undefined): void {
        const nowMs = Date.now()
        if (outcome === 'ok') {
            this.budget.recordSuccess(domain, nowMs)
            return
        }
        if (outcome === 'rate_limited' || outcome === 'server_error') {
            this.budget.recordRetryAfter(domain, nowMs, retryAfterMs ?? this.options.defaultRetryAfterMs)
            this.budget.recordBackoff(domain, nowMs)
            return
        }
        if (outcome === 'timeout' || outcome === 'error') {
            this.budget.recordBackoff(domain, nowMs)
            return
        }
        if (outcome === 'redirect_deferred') {
            // The budget of the redirect target refused, which says nothing about this domain.
            return
        }
        if (outcome === 'forbidden') {
            // One 403 is a missing image. A run of them is an anti-bot rule, so they count toward
            // the breaker without cutting the rate that a single missing image would not deserve.
            this.budget.recordRefusal(domain, nowMs)
        }
    }

    /**
     * A redirect target spends a token from its own domain, so the rate a site receives counts the
     * hops that land on it as well as the URLs keyed to it.
     *
     * The outcome of the whole chain is still recorded against the domain the URL was keyed by. A
     * site that redirects every image to a CDN therefore opens its own breaker when that CDN fails.
     * The rate limit, which is what protects the CDN, is applied to the CDN either way.
     */
    private async authorizeRedirect(url: URL, deadlineMs: number): Promise<RedirectDecision> {
        const grant = this.budget.take(politenessKey(url.hostname), Date.now(), deadlineMs)
        if (!grant.granted) {
            // Deferred rather than refused, so no sighting is written. All three refusal reasons
            // say the target cannot be reached now, not that this URL is unreachable.
            return 'defer'
        }
        if (grant.waitMs > 0) {
            await delay(grant.waitMs)
        }
        return 'allow'
    }
}
