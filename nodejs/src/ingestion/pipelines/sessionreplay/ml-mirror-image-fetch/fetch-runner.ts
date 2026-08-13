import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'
import { delay } from '~/common/utils/utils'

import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { FrontierPublisher } from './frontier-publisher'
import { HostBudget } from './host-budget'
import { FetchOutcome, ImageFetchResult, ImageFetcher, RedirectDecision } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'

/** Why a URL never reached a request. Shares `rate_limited` with the response of the same name, because both mean the site asked us to wait. */
export type ShedReason = 'breaker_open' | 'rate_limited' | 'deadline' | 'connection_limit'

/** A URL that ran out of moves. It is recorded so it stops coming back. Requirement 12. */
export const HOPS_EXHAUSTED = 'hops_exhausted'

export type AttemptOutcome = FetchOutcome | ShedReason | typeof HOPS_EXHAUSTED

export interface FetchAttempt {
    candidate: FetchCandidate
    outcome: AttemptOutcome
    /**
     * True when the lane is done with this URL and must write it to the crawl history.
     *
     * False means the URL is coming back: it was republished to the frontier or to a delay topic,
     * or the republish failed and the next session that refers to it will offer it again. Writing
     * the crawl history for one of those would stop it ever being fetched. Requirements 12 and 24.
     */
    finished: boolean
}

export interface FetchRunnerOptions {
    /** Workers per domain. The limit itself lives in the budget, because a redirect reaches a domain without passing through this pool. */
    maxConcurrentPerDomain: number
    /**
     * Requests open across every domain at once.
     *
     * Politeness needs no cap here. The topic keys by registrable domain, so one domain lands on
     * one partition and one pod. That pod holds its rate and connection limits in memory. A cap on
     * domains would only make unrelated sites wait for each other.
     *
     * What this bounds is the pod. A body is read into a buffer, so the peak memory is roughly this
     * number times the byte limit. The sockets and the DNS lookups come with it.
     */
    maxInFlightRequests: number
    /** Wall time the whole pass may take. What it does not reach is shed and fetched again the next time a session refers to it. */
    batchBudgetMs: number
    maxBytes: number
    requestTimeoutMs: number
    maxRedirects: number
    /** Held for a 429 or a 503 that named no period, so a site that only says "slow down" still gets a pause. */
    defaultRetryAfterMs: number
}

/**
 * Outcomes that will not change if the same URL is tried again.
 *
 * Only these write a crawl history entry. A URL shed by the budget, or lost to a timeout, is left unrecorded
 * so the next session that refers to it tries again. An entry written for one of those would
 * suppress the URL for the whole crawl history TTL because a site was busy for a moment.
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

/**
 * The addon holds a 15 MB native library, and `index.ts` imports every server whatever mode the pod
 * runs. Loaded on first use rather than at import, so only a pod that follows a redirect pays for
 * it. The mirror server defers it the same way.
 */
let politenessKey: ((host: string) => string) | undefined
function getPolitenessKey(): (host: string) => string {
    if (!politenessKey) {
        const addon = require('@posthog/replay-anonymizer') as typeof import('@posthog/replay-anonymizer')
        if (typeof addon.politenessKey !== 'function') {
            throw new Error('the replay-anonymizer addon has no politenessKey: rebuild index.node')
        }
        politenessKey = addon.politenessKey
    }
    return politenessKey
}

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
 * Domains run in parallel, so one slow site delays only its own URLs. Inside a domain the worker
 * count is the connection limit and the token bucket is the rate, so a domain receives from this
 * pod exactly what an operator configured for it.
 *
 * The pass is bounded by wall time rather than by work. A batch can hold more URLs for one domain
 * than a polite rate carries in the time a Kafka batch may take, and the lane answers that by
 * fetching fewer of them.
 */
export class FetchRunner implements FetchPass {
    private readonly inFlight: ConcurrencyController

    constructor(
        private readonly fetcher: ImageFetcher,
        private readonly budget: HostBudget,
        private readonly options: FetchRunnerOptions,
        /** Absent leaves every transient outcome unrecorded, which is a loss rather than a retry. See the README. */
        private readonly publisher?: FrontierPublisher
    ) {
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN', options.maxConcurrentPerDomain)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS', options.maxInFlightRequests)
        this.inFlight = new ConcurrencyController(options.maxInFlightRequests)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES', options.maxBytes)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS', options.requestTimeoutMs)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_DEFAULT_RETRY_AFTER_MS', options.defaultRetryAfterMs)
        // Zero is meaningful for both of these, meaning no fetch at all and no redirect at all.
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
            const backQueue = byDomain.get(candidate.domain)
            if (backQueue) {
                backQueue.push(candidate)
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
     * log line. The counts answer the same question, and the hosts say where to look. A URL is page
     * content, so it appears in no log.
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
     * Every domain runs at once. A domain spends nearly all of its time waiting on its own rate
     * limit, so holding thousands of them costs a queue and a closure each, and letting only a few
     * run would make sites wait on each other for no reason of politeness.
     *
     * The requests underneath them are what is bounded, by `maxInFlightRequests`.
     */
    private async runDomains(entries: [string, FetchCandidate[]][], deadlineMs: number): Promise<FetchAttempt[]> {
        // Written into by every domain rather than concatenated afterwards. One batch can offer
        // hundreds of thousands of URLs to a single domain, and both `push(...array)` and
        // `concat` of that size exceed the argument limit of `Function.apply`.
        const attempts: FetchAttempt[] = []
        await Promise.all(
            entries.map(([domain, backQueue]) => this.runBackQueue(domain, backQueue, deadlineMs, attempts))
        )
        return attempts
    }

    /** One back queue: the crawler term for the per-host queue that a politeness limit is applied to. */
    private async runBackQueue(
        domain: string,
        backQueue: FetchCandidate[],
        deadlineMs: number,
        attempts: FetchAttempt[]
    ): Promise<void> {
        let next = 0
        // A refusal is a property of the domain, so it applies to every URL still queued for it
        // rather than only to the one that asked.
        const shedRemaining = async (reason: ShedReason): Promise<void> => {
            while (next < backQueue.length) {
                const candidate = backQueue[next++]
                ImageFetchRequestMetrics.incOutcome(reason)
                attempts.push(await this.reschedule(candidate, reason, this.budget.blockedForMs(domain, Date.now())))
            }
        }

        const worker = async (): Promise<void> => {
            while (next < backQueue.length) {
                const grant = this.budget.take(domain, Date.now(), deadlineMs)
                if (!grant.granted) {
                    await shedRemaining(grant.reason)
                    return
                }
                const candidate = backQueue[next++]
                ImageFetchRequestMetrics.observeBudgetWait(grant.waitMs / 1000)
                if (grant.waitMs > 0) {
                    await delay(grant.waitMs)
                    // The grant was made before the wait. A Retry-After or an open breaker can
                    // arrive during it, and the deadline can pass. Requirement 5.
                    const stale = this.staleAfterWait(domain, deadlineMs)
                    if (stale) {
                        this.budget.returnGrant(domain, Date.now())
                        ImageFetchRequestMetrics.incOutcome(stale)
                        attempts.push(
                            await this.reschedule(candidate, stale, this.budget.blockedForMs(domain, Date.now()))
                        )
                        continue
                    }
                }
                attempts.push(await this.fetchOne(candidate, deadlineMs))
            }
        }

        const workers = Math.min(this.options.maxConcurrentPerDomain, backQueue.length)
        await Promise.all(Array.from({ length: workers }, () => worker()))
    }

    /** Why a granted request must not go out after its wait, or null when it still may. Requirement 5. */
    private staleAfterWait(domain: string, deadlineMs: number): ShedReason | null {
        const nowMs = Date.now()
        const blocked = this.budget.blockedReason(domain, nowMs)
        if (blocked) {
            return blocked
        }
        return nowMs > deadlineMs ? 'deadline' : null
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
        // Every domain this chain touches holds one of that domain's connection slots until the
        // chain ends. A slot taken twice by one chain is held once, so a redirect back to a domain
        // already in the chain does not deadlock against itself.
        const held = new Set<string>()
        const acquire = (domain: string): boolean => {
            if (held.has(domain)) {
                return true
            }
            if (!this.budget.acquireConnection(domain, Date.now())) {
                return false
            }
            held.add(domain)
            return true
        }
        const releaseAll = (): void => {
            for (const domain of held) {
                this.budget.releaseConnection(domain, Date.now())
            }
        }

        if (!acquire(candidate.domain)) {
            // Reachable because redirects into this domain take slots the worker pool does not know
            // about. It says the domain is busy now, so nothing is written to the crawl history for it.
            ImageFetchRequestMetrics.incOutcome('connection_limit')
            return await this.reschedule(candidate, 'connection_limit', 0)
        }

        const startedAt = process.hrtime.bigint()
        let result: ImageFetchResult
        try {
            result = await this.inFlight.run({
                debugTag: candidate.domain,
                fn: () =>
                    this.fetcher.fetch(candidate.url, {
                        maxBytes: this.options.maxBytes,
                        timeoutMs: this.options.requestTimeoutMs,
                        maxRedirects: this.options.maxRedirects,
                        // The earlier of the two clocks. A wait that outlives the request would be
                        // spent and then reported as the site timing out.
                        authorizeRedirect: (url, remainingMs) =>
                            this.authorizeRedirect(
                                url,
                                Math.min(deadlineMs, Date.now() + remainingMs),
                                acquire,
                                candidate.domain
                            ),
                    }),
            })
        } catch (error) {
            // The fetcher answers with an outcome rather than a throw, so reaching here means a
            // defect. It is caught anyway: a throw would leave the other domains of this batch
            // running while the partition replays them.
            logger.error('🌐', 'ml_image_fetch_unhandled_error', {
                host: candidate.host,
                // The name only. An error message from the request layer can carry the URL, and a
                // URL is page content.
                error: error instanceof Error ? error.name : 'unknown',
            })
            ImageFetchRequestMetrics.incOutcome('error')
            return await this.reschedule(candidate, 'error', 0)
        } finally {
            releaseAll()
        }
        const durationSeconds = Number(process.hrtime.bigint() - startedAt) / 1e9

        this.applyToBudget(candidate.domain, result.outcome, result.retryAfterMs)
        ImageFetchRequestMetrics.observeRequest(result.outcome, durationSeconds, result.redirects)
        if (result.bytes) {
            ImageFetchRequestMetrics.observeBytes(result.bytes.length)
        }
        // The bytes stop here. Nothing produces them yet, and holding a batch of them would be the
        // largest memory this lane ever took.
        if (result.outcome === 'redirect_offsite' && result.redirectTarget) {
            return await this.handOff(candidate, result.redirectTarget)
        }
        if (isTerminal(result.outcome)) {
            ImageFetchRequestMetrics.observeHops(MAX_HOPS - candidate.hopsRemaining)
            return { candidate, outcome: result.outcome, finished: true }
        }
        return await this.reschedule(
            candidate,
            result.outcome,
            result.retryAfterMs ?? this.budget.blockedForMs(candidate.domain, Date.now())
        )
    }

    private applyToBudget(domain: string, outcome: FetchOutcome, retryAfterMs: number | undefined): void {
        const nowMs = Date.now()
        if (outcome === 'ok') {
            this.budget.recordSuccess(domain, nowMs)
            return
        }
        if (outcome === 'rate_limited' || outcome === 'server_error') {
            // The whole domain is held when the site asked to be left alone, meaning a 429 or any
            // response that named a period. A one-off 500 gets the rate cut and the breaker count
            // instead: it says this request failed, not that the site wants silence for a minute.
            if (outcome === 'rate_limited' || retryAfterMs !== undefined) {
                this.budget.recordRetryAfter(domain, nowMs, retryAfterMs ?? this.options.defaultRetryAfterMs)
            }
            this.budget.recordBackoff(domain, nowMs)
            return
        }
        if (outcome === 'timeout' || outcome === 'error') {
            this.budget.recordBackoff(domain, nowMs)
            return
        }
        if (outcome === 'redirect_deferred' || outcome === 'unsupported_encoding') {
            // Neither says anything about the load this domain is under.
            return
        }
        if (outcome === 'forbidden') {
            // One 403 is a missing image, which is no reason to slow down. A run of them is an
            // anti-bot rule, which the breaker has to catch.
            this.budget.recordRefusal(domain, nowMs)
        }
    }

    /**
     * A redirect target spends a token from its own domain, so the rate a site receives counts the
     * hops that land on it as well as the URLs keyed to it.
     *
     * The outcome of the whole chain is still recorded against the domain the URL was keyed by, so
     * a site that redirects every image to a CDN opens its own breaker when that CDN fails. The CDN
     * still gets the rate limit, which is the part that protects it.
     */
    /**
     * Put a URL back for another try, or give up on it.
     *
     * A URL with no hops left is recorded, so it stops coming back and the lane stops spending
     * requests on it. Requirement 12. Anything else goes to the delay topic whose period covers the
     * wait, and is not recorded, because it has not been answered yet. Requirements 13 to 15.
     *
     * Without a publisher the URL is simply left unrecorded. The next session that refers to it
     * offers it again, which the mirror's ref cache delays by however long that ref stays cached.
     */
    private async reschedule(
        candidate: FetchCandidate,
        outcome: AttemptOutcome,
        waitMs: number
    ): Promise<FetchAttempt> {
        if (candidate.hopsRemaining <= 1) {
            ImageFetchRequestMetrics.incOutcome(HOPS_EXHAUSTED)
            ImageFetchRequestMetrics.observeHops(MAX_HOPS)
            return { candidate, outcome: HOPS_EXHAUSTED, finished: true }
        }
        if (!this.publisher) {
            return { candidate, outcome, finished: false }
        }
        const target = { url: candidate.url, host: candidate.host, domain: candidate.domain }
        await this.publisher.republish(candidate, target, 'retry', waitMs)
        return { candidate, outcome, finished: false }
    }

    /**
     * Send a redirect target to the consumer that owns its domain.
     *
     * The hop is not followed here. That domain's rate, breaker, and connection count live in the
     * pod holding its partition, and following the hop from this pod would spend none of them.
     * Requirement 7.
     */
    private async handOff(candidate: FetchCandidate, target: { url: string; host: string }): Promise<FetchAttempt> {
        if (candidate.hopsRemaining <= 1) {
            ImageFetchRequestMetrics.incOutcome(HOPS_EXHAUSTED)
            return { candidate, outcome: HOPS_EXHAUSTED, finished: true }
        }
        if (!this.publisher) {
            return { candidate, outcome: 'redirect_offsite', finished: false }
        }
        const domain = getPolitenessKey()(target.host)
        await this.publisher.republish(candidate, { ...target, domain }, 'redirect')
        return { candidate, outcome: 'redirect_offsite', finished: false }
    }

    private async authorizeRedirect(
        url: URL,
        deadlineMs: number,
        acquire: (domain: string) => boolean,
        sourceDomain: string
    ): Promise<RedirectDecision> {
        // The same function the producer keys the topic with, called through the addon rather than
        // reimplemented here. One public suffix list answers for both, so the two cannot drift.
        const domain = getPolitenessKey()(url.hostname)
        // Another operator owns this target, so this pod must not fetch it. Requirement 7.
        if (domain !== sourceDomain) {
            return 'elsewhere'
        }
        if (!acquire(domain)) {
            return 'defer'
        }
        const grant = this.budget.take(domain, Date.now(), deadlineMs)
        if (!grant.granted) {
            // Deferred rather than refused, so nothing is written to the crawl history. Every refusal reason here
            // is about this moment rather than about the URL.
            return 'defer'
        }
        // Counted like the wait of a first request, so the histogram covers every politeness wait
        // this lane takes rather than only the ones outside a redirect.
        ImageFetchRequestMetrics.observeBudgetWait(grant.waitMs / 1000)
        if (grant.waitMs > 0) {
            await delay(grant.waitMs)
        }
        return 'allow'
    }
}
