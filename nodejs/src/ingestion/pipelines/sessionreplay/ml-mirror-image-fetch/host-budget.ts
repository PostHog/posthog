export interface HostBudgetOptions {
    /** The ceiling for one registrable domain. Only a backoff moves a domain off it, and always downward. */
    requestsPerSecond: number
    /** Tokens a domain holds while idle, so a domain seen once an hour can send a few requests together. */
    burst: number
    /** Connections open to one domain at once. This counts them rather than the caller's worker pool, because a redirect reaches a domain without going through that pool. */
    maxConcurrent: number
    breakerFailures: number
    breakerCooldownMs: number
    /** The longest a domain stays blocked. It bounds the doubling cooldown and a `Retry-After` header alike. */
    breakerMaxCooldownMs: number
    maxTrackedDomains: number
}

export type BudgetGrant =
    | { granted: true; waitMs: number }
    | { granted: false; reason: 'breaker_open' | 'rate_limited' | 'deadline' }

interface DomainState {
    inFlight: number
    tokens: number
    lastRefillMs: number
    requestsPerSecond: number
    failureScore: number
    cooldownMs: number
    blockedUntilMs: number
    blockedReason: 'breaker_open' | 'rate_limited'
}

/** A domain's rate never falls below the configured rate divided by this. */
const MIN_RATE_DIVISOR = 16

/** Domains checked for an idle one before an eviction falls back to the oldest entry. */
const EVICTION_SCAN = 16

/**
 * How fast this pod may send to one registrable domain.
 *
 * The domain rather than the host, because one operator can serve images from many hostnames, and a
 * rate limit protects the operator. The topic uses the same key, so a domain lands on one partition
 * and one pod, and this budget is then the whole rate that domain receives from this lane. A
 * rebalance can put two pods on one domain for a few seconds, which doubles the rate for that long.
 * No counter across pods closes that window.
 *
 * A restart loses this state, including an open breaker, so a restart sends one more round of
 * requests to a failing site before the breaker opens again.
 */
export class HostBudget {
    private readonly domains = new Map<string, DomainState>()

    constructor(private readonly options: HostBudgetOptions) {
        // These values arrive from the environment, where a typo parses to NaN. A NaN rate makes
        // every wait NaN and every comparison against it false, so the rate limit stops existing.
        for (const [name, value] of Object.entries(options)) {
            if (!Number.isFinite(value) || value <= 0) {
                throw new Error(`the image fetch host budget needs a positive ${name}, got ${value}`)
            }
        }
    }

    /**
     * Take the right to send one request to `domain`, or learn why this pod must not send to it.
     *
     * A grant carries the time the caller must wait before it sends. The grant already spent the
     * token, so a caller that waits keeps the rate exact, and a caller that drops the grant only
     * slows the domain down. A grant that lands after `deadlineMs` is refused instead, because
     * nobody sends it and the next batch still waits the token out.
     */
    public take(domain: string, nowMs: number, deadlineMs: number): BudgetGrant {
        const state = this.stateFor(domain, nowMs)
        if (state.blockedUntilMs > nowMs) {
            return { granted: false, reason: state.blockedReason }
        }
        this.refill(state, nowMs)
        const waitMs = state.tokens >= 1 ? 0 : Math.ceil(((1 - state.tokens) / state.requestsPerSecond) * 1000)
        if (nowMs + waitMs > deadlineMs) {
            return { granted: false, reason: 'deadline' }
        }
        state.tokens -= 1
        return { granted: true, waitMs }
    }

    /**
     * Why this pod must not send to the domain, or null when it may.
     *
     * A caller that waited for a token asks again before it sends. A `Retry-After` or an open
     * breaker can arrive during a wait, and a request sent after that reaches a site which just
     * asked to be left alone. Requirement 5.
     */
    public blockedReason(domain: string, nowMs: number): 'breaker_open' | 'rate_limited' | null {
        const state = this.domains.get(domain)
        return state && state.blockedUntilMs > nowMs ? state.blockedReason : null
    }

    /**
     * How long the domain stays blocked, so a retry can wait that long rather than guess.
     *
     * An unknown domain reads as not blocked, and this creates no entry for it. An entry would let
     * a question about one domain evict the hold on another.
     */
    public blockedForMs(domain: string, nowMs: number): number {
        const state = this.domains.get(domain)
        return state ? Math.max(0, state.blockedUntilMs - nowMs) : 0
    }

    /**
     * Give back a token for a request that never went out.
     *
     * The rate limits what leaves this pod, so a grant that went stale during its wait must not
     * count against the domain. The burst caps the return, so a return cannot create capacity.
     */
    public returnGrant(domain: string, nowMs: number): void {
        const state = this.stateFor(domain, nowMs)
        state.tokens = Math.min(this.options.burst, state.tokens + 1)
    }

    /**
     * Take one of the domain's connection slots, or report that they are all taken.
     *
     * The rate limit and the connection limit answer different questions: how often we may start,
     * and how many we may hold open. A slow site makes the second one bind, and a redirect target
     * reaches this without passing through the per-domain worker pool that would otherwise bound it.
     */
    public acquireConnection(domain: string, nowMs: number): boolean {
        const state = this.stateFor(domain, nowMs)
        if (state.inFlight >= this.options.maxConcurrent) {
            return false
        }
        state.inFlight += 1
        return true
    }

    public releaseConnection(domain: string): void {
        const state = this.domains.get(domain)
        if (state) {
            state.inFlight = Math.max(0, state.inFlight - 1)
        }
    }

    public recordSuccess(domain: string, nowMs: number): void {
        const state = this.stateFor(domain, nowMs)
        // Decremented rather than cleared. A domain that fails two requests for every one it answers
        // never reaches a run of failures, and a counter that resets never opens its breaker.
        state.failureScore = Math.max(0, state.failureScore - 1)
        const step = this.options.requestsPerSecond / 8
        state.requestsPerSecond = Math.min(this.options.requestsPerSecond, state.requestsPerSecond + step)
        // The doubling ladder clears only once the rate is fully back, so a site that fails,
        // recovers for one request, and fails again keeps escalating. It does not restart at the
        // base cooldown every time.
        if (state.requestsPerSecond >= this.options.requestsPerSecond) {
            state.cooldownMs = 0
        }
    }

    /**
     * A site said it is unhappy. Halve the rate, and count toward the breaker.
     *
     * The rate halves on the first signal rather than after a threshold. A cut that comes too early
     * costs one slower domain. A cut that comes too late adds load to a site that asked us to stop.
     *
     * The tokens go with it. A domain holds a burst while it is idle, so without this the URLs
     * already queued behind the failed one would leave at the old rate and the cut would reach only
     * the URLs after them. Requirement 16.
     */
    public recordBackoff(domain: string, nowMs: number): void {
        const state = this.stateFor(domain, nowMs)
        const floor = this.options.requestsPerSecond / MIN_RATE_DIVISOR
        state.requestsPerSecond = Math.max(floor, state.requestsPerSecond / 2)
        state.tokens = 0
        this.countTowardBreaker(state, nowMs)
    }

    /**
     * A refusal that says nothing about load, such as a 403 from an anti-bot rule.
     *
     * It counts toward the breaker, because a run of refusals means the site refuses this bot and
     * more requests only add to that. It leaves the rate alone, because one refused image is an
     * ordinary answer that must not slow down the images beside it.
     */
    public recordRefusal(domain: string, nowMs: number): void {
        this.countTowardBreaker(this.stateFor(domain, nowMs), nowMs)
    }

    private countTowardBreaker(state: DomainState, nowMs: number): void {
        state.failureScore += 1
        if (state.failureScore < this.options.breakerFailures) {
            return
        }
        // Doubled from the last cooldown rather than reset, so a site that keeps failing after the
        // breaker closes gets a longer pause each time rather than a probe on a fixed beat.
        state.cooldownMs = Math.min(
            state.cooldownMs > 0 ? state.cooldownMs * 2 : this.options.breakerCooldownMs,
            this.options.breakerMaxCooldownMs
        )
        // Extended rather than replaced. A breaker that opens inside an hour-long hold must not
        // shorten that hold to its own cooldown.
        const openUntilMs = nowMs + state.cooldownMs
        if (openUntilMs > state.blockedUntilMs) {
            state.blockedUntilMs = openUntilMs
            state.blockedReason = 'breaker_open'
        }
        state.failureScore = 0
    }

    /**
     * Hold the domain for the period a `Retry-After` header asked for.
     *
     * The clamp is necessary because a site can name any period, and an unclamped one holds a
     * domain in this pod's memory for as long as the pod lives.
     */
    public recordRetryAfter(domain: string, nowMs: number, retryAfterMs: number): void {
        const state = this.stateFor(domain, nowMs)
        const held = Math.min(Math.max(retryAfterMs, 0), this.options.breakerMaxCooldownMs)
        // The reason moves only when this hold wins. A domain already held by an open breaker would
        // otherwise report every later shed as a rate limit, which hides the breaker from the
        // metric that exists to show it.
        if (nowMs + held > state.blockedUntilMs) {
            state.blockedUntilMs = nowMs + held
            state.blockedReason = 'rate_limited'
        }
    }

    public get trackedDomains(): number {
        return this.domains.size
    }

    /** Domains this dropped while they were still blocked, which resumes traffic to a site that asked us to wait. */
    public evictedWhileBlocked = 0

    public blockedDomains(nowMs: number): number {
        let blocked = 0
        for (const state of this.domains.values()) {
            if (state.blockedUntilMs > nowMs) {
                blocked++
            }
        }
        return blocked
    }

    private refill(state: DomainState, nowMs: number): void {
        const elapsedMs = Math.max(0, nowMs - state.lastRefillMs)
        state.lastRefillMs = nowMs
        state.tokens = Math.min(this.options.burst, state.tokens + (elapsedMs / 1000) * state.requestsPerSecond)
    }

    private stateFor(domain: string, nowMs: number): DomainState {
        const existing = this.domains.get(domain)
        if (existing) {
            // Re-inserted so that the map orders by last use, which the eviction below reads.
            this.domains.delete(domain)
            this.domains.set(domain, existing)
            return existing
        }
        this.evictIfFull(nowMs)
        const state: DomainState = {
            inFlight: 0,
            tokens: this.options.burst,
            lastRefillMs: nowMs,
            requestsPerSecond: this.options.requestsPerSecond,
            failureScore: 0,
            cooldownMs: 0,
            blockedUntilMs: 0,
            blockedReason: 'breaker_open',
        }
        this.domains.set(domain, state)
        return state
    }

    /**
     * An evicted domain loses its block, so the scan prefers an idle domain. When the map holds
     * only blocked domains the oldest one goes anyway, because a refusal to evict grows the map
     * without a bound and the memory limit is the harder failure.
     */
    private evictIfFull(nowMs: number): void {
        if (this.domains.size < this.options.maxTrackedDomains) {
            return
        }
        let oldest: string | undefined
        let scanned = 0
        for (const [domain, state] of this.domains) {
            if (state.inFlight > 0) {
                // Never evicted. A slot is released by domain name, so a lost entry leaks every
                // slot it held and the domain can then hold more than its limit. The map cannot
                // grow without a bound this way, because the pod caps its requests in flight.
                continue
            }
            oldest = oldest ?? domain
            if (state.blockedUntilMs <= nowMs) {
                this.domains.delete(domain)
                return
            }
            if (++scanned >= EVICTION_SCAN) {
                break
            }
        }
        if (oldest) {
            // Counted only when the entry really was blocked.
            const evicted = this.domains.get(oldest)
            this.domains.delete(oldest)
            if (evicted && evicted.blockedUntilMs > nowMs) {
                this.evictedWhileBlocked++
            }
        }
    }
}
