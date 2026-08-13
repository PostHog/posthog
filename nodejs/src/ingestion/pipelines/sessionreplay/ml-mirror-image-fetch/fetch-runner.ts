import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'
import { delay } from '~/common/utils/utils'

import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { FrontierPublisher } from './frontier-publisher'
import { HostBudget } from './host-budget'
import { FetchOutcome, ImageFetchResult, ImageFetcher, RedirectDecision } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'
import { politenessKey } from './politeness-key'

/** Why a URL never reached a request. It shares `rate_limited` with the response of the same name, because both mean the site asked us to wait. */
export type ShedReason = 'breaker_open' | 'rate_limited' | 'deadline' | 'connection_limit'

/** A URL that ran out of hops. The lane records it so it stops coming back. Requirement 12. */
export const HOPS_EXHAUSTED = 'hops_exhausted'

export type AttemptOutcome = FetchOutcome | ShedReason | typeof HOPS_EXHAUSTED

export interface FetchAttempt {
    candidate: FetchCandidate
    outcome: AttemptOutcome
    /**
     * True when the lane is done with this URL and must write it to the crawl history.
     *
     * False means the URL comes back, from a republish to the frontier or to a delay topic, or from
     * a failed republish. A crawl history entry for one of those stops it ever being fetched.
     * Requirements 12 and 24.
     */
    finished: boolean
    /**
     * True when the URL was meant to go back to Kafka and did not.
     *
     * Nothing else holds it, so its offset must not commit. The URL is otherwise gone until a
     * session refers to the same image again. Requirement 21.
     */
    lost: boolean
}

export interface FetchRunnerOptions {
    /** Workers per domain. The limit itself lives in the budget, because a redirect reaches a domain without passing through this pool. */
    maxConcurrentPerDomain: number
    /**
     * Requests open across every domain at once. This bounds the pod rather than politeness.
     *
     * The lane reads a body into a buffer, so the peak memory is about this number times the byte
     * limit. The sockets and the DNS lookups come with it.
     */
    maxInFlightRequests: number
    /** Wall time the whole pass may take. The lane sheds a URL it does not reach, and fetches it again when a session next refers to it. */
    batchBudgetMs: number
    maxBytes: number
    requestTimeoutMs: number
    maxRedirects: number
    /** Used for a 429 or a 503 that named no period, so a site that only says "slow down" still gets a pause. */
    defaultRetryAfterMs: number
}

/**
 * Outcomes that will not change if the lane tries the same URL again.
 *
 * Only these write a crawl history entry. The lane leaves a URL shed by the budget, or lost to a
 * timeout, unrecorded, because it goes back to a delay topic and comes round again. An entry for one
 * of those would suppress the URL for the whole crawl history TTL because a site was busy for a
 * moment.
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
    // A property of the origin rather than of the moment, so a retry meets the same response and
    // spends a hop for nothing.
    'unsupported_encoding',
])

/**
 * URLs one pass puts back after a shed, across every domain in it.
 *
 * A shed happens under overload, and one back queue can hold every URL of a batch. Republishing all
 * of them answers overload with more Kafka traffic, and the same URLs arrive again a minute later
 * having each spent a hop. Past this the rest are left unrecorded, so the mirror offers them again.
 *
 * One allowance for the pass rather than one for each domain, because domains run at the same time.
 * A per-domain cap multiplies by however many domains a batch touches, and a batch that offers
 * URLs across hundreds of them would open that many times this number of produces at once.
 */
const MAX_SHED_REPUBLISHED_PER_PASS = 1000

/** What is left of the pass allowance. Read and written between awaits, so a domain never sees a torn value. */
interface ShedAllowance {
    remaining: number
}

/** Hosts named in one batch-level log line, bounded so one bad batch cannot log a host list of its own size. */
const MAX_LOGGED_HOSTS = 5

/** These values come from the environment, where a typo parses to NaN and switches a politeness control off. */
function requirePositive(name: string, value: number): number {
    if (!Number.isFinite(value) || value <= 0) {
        throw new Error(`${name} must be a positive number, got ${value}`)
    }
    return value
}

export function isTerminal(outcome: AttemptOutcome): boolean {
    return TERMINAL_OUTCOMES.has(outcome)
}

/** What the consumer needs of the fetch pass, so its tests use the real contract rather than a cast. */
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
 * Wall time bounds the pass rather than work. A batch can hold more URLs for one domain than a
 * polite rate carries in the time a Kafka batch may take, and the lane then fetches fewer of them.
 */
export class FetchRunner implements FetchPass {
    private readonly inFlight: ConcurrencyController

    constructor(
        private readonly fetcher: ImageFetcher,
        private readonly budget: HostBudget,
        private readonly options: FetchRunnerOptions,
        /** Required, because without it every transient outcome becomes a loss rather than a retry. */
        private readonly publisher: FrontierPublisher
    ) {
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN', options.maxConcurrentPerDomain)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS', options.maxInFlightRequests)
        this.inFlight = new ConcurrencyController(options.maxInFlightRequests)
        ImageFetchRequestMetrics.trackBudget(budget, this.inFlight)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES', options.maxBytes)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS', options.requestTimeoutMs)
        requirePositive('SESSION_RECORDING_ML_IMAGE_FETCH_DEFAULT_RETRY_AFTER_MS', options.defaultRetryAfterMs)
        // Zero is meaningful for both, and means no fetch at all and no redirect at all.
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

        const attempts = await this.runDomains([...byDomain], deadlineMs, { remaining: MAX_SHED_REPUBLISHED_PER_PASS })
        this.logFailures(attempts)
        return attempts
    }

    /**
     * One line for each outcome of the whole pass, because a site that is down turns every URL of a
     * batch into a log line. The counts answer the same question, and the hosts say where to look.
     *
     * A URL is page content, so it appears in no log.
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
     * limit, so thousands of them cost a queue and a closure each, and a cap on domains would make
     * unrelated sites wait for each other for no reason of politeness.
     *
     * `maxInFlightRequests` bounds the requests underneath them.
     */
    private async runDomains(
        entries: [string, FetchCandidate[]][],
        deadlineMs: number,
        allowance: ShedAllowance
    ): Promise<FetchAttempt[]> {
        // Every domain writes into this array rather than concatenating afterwards. One batch can
        // offer hundreds of thousands of URLs to a single domain, and both `push(...array)` and
        // `concat` of that size exceed the argument limit of `Function.apply`.
        const attempts: FetchAttempt[] = []
        await Promise.all(
            entries.map(([domain, backQueue]) => this.runBackQueue(domain, backQueue, deadlineMs, attempts, allowance))
        )
        return attempts
    }

    /** A back queue is the crawler term for the queue of one registrable domain, which a politeness limit applies to. */
    private async runBackQueue(
        domain: string,
        backQueue: FetchCandidate[],
        deadlineMs: number,
        attempts: FetchAttempt[],
        allowance: ShedAllowance
    ): Promise<void> {
        let next = 0
        // A refusal is a property of the domain, so it applies to every URL still queued for it.
        const shedRemaining = async (reason: ShedReason, first?: FetchCandidate): Promise<void> => {
            const shed = first ? [first, ...backQueue.slice(next)] : backQueue.slice(next)
            next = backQueue.length
            if (shed.length === 0) {
                return
            }
            ImageFetchRequestMetrics.incOutcome(reason, shed.length)
            const waitMs = this.budget.blockedForMs(domain, Date.now())
            // Taken before the first await, so two domains shedding at once cannot both read the
            // same remainder and spend it twice.
            const takes = Math.min(shed.length, allowance.remaining)
            allowance.remaining -= takes
            // Together rather than one after another. A shed runs once the pass deadline has passed,
            // and one awaited produce for each of tens of thousands of URLs would run past
            // `max.poll.interval.ms` and lose the partition in the middle of the batch.
            const republished = await Promise.all(
                shed.slice(0, takes).map((candidate) => this.reschedule(candidate, reason, waitMs))
            )
            for (const attempt of republished) {
                attempts.push(attempt)
            }
            for (const candidate of shed.slice(takes)) {
                attempts.push({ candidate, outcome: reason, finished: false, lost: false })
            }
            if (shed.length > takes) {
                ImageFetchRequestMetrics.incShedDropped(shed.length - takes)
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
                    // The budget granted this before the wait. A `Retry-After` or an open breaker
                    // can arrive during the wait, and the deadline can pass. Requirement 5.
                    const stale = this.staleAfterWait(domain, deadlineMs)
                    if (stale) {
                        this.budget.returnGrant(domain, Date.now())
                        // The whole back queue, not this URL alone. Whatever went stale during the
                        // wait is a property of the domain, so it holds for every URL still queued
                        // for it. Requirement 16.
                        await shedRemaining(stale, candidate)
                        return
                    }
                }
                attempts.push(await this.fetchOne(candidate, deadlineMs))
            }
        }

        const workers = Math.min(this.options.maxConcurrentPerDomain, backQueue.length)
        await Promise.all(Array.from({ length: workers }, () => worker()))
    }

    /** Why a granted request must not go out after its wait, or null when it may still go out. Requirement 5. */
    private staleAfterWait(domain: string, deadlineMs: number): ShedReason | null {
        const nowMs = Date.now()
        const blocked = this.budget.blockedReason(domain, nowMs)
        if (blocked) {
            return blocked
        }
        return nowMs > deadlineMs ? 'deadline' : null
    }

    /**
     * The request keeps its whole configured timeout even when the pass deadline is closer.
     *
     * A request that the batch clock cut short would time out through no fault of the site, and the
     * budget would read that as the site failing. So the deadline decides whether a request starts,
     * and never how long it may take. One pass can therefore run to `batchBudgetMs` plus one
     * request timeout, which is still far inside Kafka's max.poll.interval.ms.
     */
    private async fetchOne(candidate: FetchCandidate, deadlineMs: number): Promise<FetchAttempt> {
        // One slot, held until the chain ends. A chain reaches only its own domain, because
        // `isOffsite` refuses every other target, and the set makes a second take of the same
        // domain free so a redirect back to it cannot deadlock against itself.
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
                this.budget.releaseConnection(domain)
            }
        }

        if (!acquire(candidate.domain)) {
            // One setting feeds both the worker count and this limit, so the pool already holds a
            // domain to the same number and nothing gets here today. The budget is where the limit
            // belongs, so the check stays. A refusal means the domain is busy now, which is not a
            // fact about the URL, so the lane writes no crawl history entry for it.
            this.budget.returnGrant(candidate.domain, Date.now())
            ImageFetchRequestMetrics.incOutcome('connection_limit')
            return await this.reschedule(candidate, 'connection_limit', 0)
        }

        const startedAt = process.hrtime.bigint()
        let outcome: ImageFetchResult | { shed: ShedReason }
        try {
            outcome = await this.inFlight.run<ImageFetchResult | { shed: ShedReason }>({
                debugTag: candidate.domain,
                fn: () => {
                    // The pod queue is the third place a request waits, after the token bucket and
                    // the connection limit, and it can hold a request longest because its slots
                    // serve every domain this pod owns. A sibling request can meet a `Retry-After`
                    // while this one queues. Requirement 5.
                    const stale = this.staleAfterWait(candidate.domain, deadlineMs)
                    if (stale) {
                        return Promise.resolve({ shed: stale })
                    }
                    return this.fetcher.fetch(candidate.url, {
                        maxBytes: this.options.maxBytes,
                        timeoutMs: this.options.requestTimeoutMs,
                        maxRedirects: this.options.maxRedirects,
                        isOffsite: (url) => politenessKey(url.hostname) !== candidate.domain,
                        // The earlier of the two clocks, because a wait that outlives the request
                        // reports the site as timing out.
                        authorizeRedirect: (url, remainingMs) =>
                            this.authorizeRedirect(
                                Math.min(deadlineMs, Date.now() + remainingMs),
                                acquire,
                                candidate.domain
                            ),
                    })
                },
            })
        } catch (error) {
            // The fetcher answers with an outcome rather than a throw, so a throw here means a
            // defect. The catch stays because a throw would leave the other domains of this batch
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
        if ('shed' in outcome) {
            this.budget.returnGrant(candidate.domain, Date.now())
            ImageFetchRequestMetrics.incOutcome(outcome.shed)
            return await this.reschedule(
                candidate,
                outcome.shed,
                this.budget.blockedForMs(candidate.domain, Date.now())
            )
        }
        const result = outcome
        const durationSeconds = Number(process.hrtime.bigint() - startedAt) / 1e9

        this.applyToBudget(candidate.domain, result.outcome, result.retryAfterMs)
        ImageFetchRequestMetrics.observeRequest(result.outcome, durationSeconds, result.redirects)
        if (result.bytes) {
            ImageFetchRequestMetrics.observeBytes(result.bytes.length)
        }
        if (result.outcome === 'redirect_offsite' && result.redirectTarget) {
            return await this.handOff(candidate, result.redirectTarget)
        }
        if (isTerminal(result.outcome)) {
            ImageFetchRequestMetrics.observeHops(MAX_HOPS - candidate.hopsRemaining)
            return { candidate, outcome: result.outcome, finished: true, lost: false }
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
            // The lane holds the whole domain when the site asked to be left alone, which means a
            // 429 or any response that named a period. A one-off 500 gets the rate cut and the
            // breaker count instead, because it says this request failed and nothing more.
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
            // anti-bot rule, which the breaker must catch.
            this.budget.recordRefusal(domain, nowMs)
        }
    }

    /**
     * Put a URL back for another try, or give up on it.
     *
     * The lane records a URL with no hops left, so it stops coming back and stops costing requests.
     * Requirement 12. Everything else goes to the delay topic whose period covers the wait, and the
     * lane records nothing, because the URL has no answer yet. Requirements 13 to 15.
     */
    private async reschedule(
        candidate: FetchCandidate,
        outcome: AttemptOutcome,
        waitMs: number
    ): Promise<FetchAttempt> {
        if (candidate.hopsRemaining <= 1) {
            ImageFetchRequestMetrics.incOutcome(HOPS_EXHAUSTED)
            ImageFetchRequestMetrics.observeHops(MAX_HOPS)
            return { candidate, outcome: HOPS_EXHAUSTED, finished: true, lost: false }
        }
        const target = { url: candidate.url, host: candidate.host, domain: candidate.domain }
        const republished = await this.publisher.republish(candidate, target, 'retry', waitMs)
        return { candidate, outcome, finished: false, lost: !republished }
    }

    /**
     * Send a redirect target to the consumer that owns its domain.
     *
     * This pod does not follow the hop. That domain's rate, breaker, and connection count live in
     * the pod holding its partition, and a hop followed from this pod spends none of them.
     * Requirement 7.
     */
    private async handOff(candidate: FetchCandidate, target: { url: string; host: string }): Promise<FetchAttempt> {
        if (candidate.hopsRemaining <= 1) {
            ImageFetchRequestMetrics.incOutcome(HOPS_EXHAUSTED)
            ImageFetchRequestMetrics.observeHops(MAX_HOPS)
            return { candidate, outcome: HOPS_EXHAUSTED, finished: true, lost: false }
        }
        const domain = politenessKey(target.host)
        const republished = await this.publisher.republish(candidate, { ...target, domain }, 'redirect')
        return { candidate, outcome: 'redirect_offsite', finished: false, lost: !republished }
    }

    /** The target belongs to `domain`, because `isOffsite` already refused every other one. A hop spends a token like a first request. */
    private async authorizeRedirect(
        deadlineMs: number,
        acquire: (domain: string) => boolean,
        domain: string
    ): Promise<RedirectDecision> {
        if (!acquire(domain)) {
            return 'defer'
        }
        const grant = this.budget.take(domain, Date.now(), deadlineMs)
        if (!grant.granted) {
            // Deferred rather than refused, so the lane writes no crawl history entry. Every
            // refusal reason here is about this moment rather than about the URL.
            return 'defer'
        }
        ImageFetchRequestMetrics.observeBudgetWait(grant.waitMs / 1000)
        if (grant.waitMs > 0) {
            await delay(grant.waitMs)
            // A `Retry-After` or an open breaker can arrive while a redirect waits, exactly as it
            // can while a first request waits. Requirement 5.
            if (this.staleAfterWait(domain, deadlineMs)) {
                this.budget.returnGrant(domain, Date.now())
                return 'defer'
            }
        }
        return 'allow'
    }
}
