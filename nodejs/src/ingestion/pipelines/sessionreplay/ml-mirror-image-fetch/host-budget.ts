export interface HostBudgetOptions {
    requestsPerSecond: number
    burst: number
    maxConcurrent: number
    breakerFailures: number
    breakerCooldownMs: number
    breakerMaxCooldownMs: number
    maxTrackedDomains: number
    random?: () => number
}

export type BudgetBlockReason = 'breaker_open' | 'backoff' | 'deadline' | 'origin_map_full'
export type BudgetGrant =
    | { granted: true; waitMs: number; halfOpenProbe: boolean; reservedStartAtMs: number | null }
    | { granted: false; reason: BudgetBlockReason; waitMs: number }

const EVICTION_SCAN_LIMIT = 64

interface OriginState {
    inFlight: number
    configurationRequests: number
    tokens: number
    lastRefillMs: number
    lastRequestStartedAtMs: number | null
    reservedStartTimesMs: number[]
    crawlDelayMs: number
    consecutiveTransientFailures: number
    blockedUntilMs: number
    breakerOpen: boolean
    halfOpenProbeInFlight: boolean
}

export class HostBudget {
    private readonly origins = new Map<string, OriginState>()
    private readonly random: () => number

    constructor(private readonly options: HostBudgetOptions) {
        for (const [name, value] of Object.entries(options)) {
            if (name !== 'random' && (!Number.isFinite(value) || (value as number) <= 0)) {
                throw new Error(`the image fetch origin budget needs a positive ${name}, got ${value}`)
            }
        }
        this.random = options.random ?? Math.random
    }

    public take(origin: string, nowMs: number, deadlineMs: number, ignoreImageDelay = false): BudgetGrant {
        const state = this.stateFor(origin, nowMs)
        if (!state) {
            return { granted: false, reason: 'origin_map_full', waitMs: 0 }
        }
        let halfOpenProbe = false
        if (!ignoreImageDelay) {
            if (state.blockedUntilMs > nowMs) {
                return {
                    granted: false,
                    reason: state.breakerOpen ? 'breaker_open' : 'backoff',
                    waitMs: state.blockedUntilMs - nowMs,
                }
            }
            if (state.breakerOpen) {
                if (state.halfOpenProbeInFlight) {
                    return { granted: false, reason: 'breaker_open', waitMs: this.options.breakerCooldownMs }
                }
                state.halfOpenProbeInFlight = true
                halfOpenProbe = true
            }
        }
        this.refill(state, nowMs)
        const tokenWaitMs =
            state.tokens >= 1 ? 0 : Math.ceil(((1 - state.tokens) / this.options.requestsPerSecond) * 1000)
        const previousStartMs = Math.max(
            state.lastRequestStartedAtMs ?? Number.NEGATIVE_INFINITY,
            ...state.reservedStartTimesMs
        )
        const crawlWaitMs = ignoreImageDelay ? 0 : Math.max(0, previousStartMs + state.crawlDelayMs - nowMs)
        const waitMs = Math.max(tokenWaitMs, crawlWaitMs)
        if (nowMs + waitMs > deadlineMs) {
            if (!ignoreImageDelay && state.breakerOpen) {
                state.halfOpenProbeInFlight = false
            }
            return { granted: false, reason: 'deadline', waitMs }
        }
        state.tokens -= 1
        const reservedStartAtMs = ignoreImageDelay ? null : nowMs + waitMs
        if (reservedStartAtMs !== null) {
            state.reservedStartTimesMs.push(reservedStartAtMs)
        }
        return { granted: true, waitMs, halfOpenProbe, reservedStartAtMs }
    }

    public markRequestStarted(origin: string, nowMs: number, reservedStartAtMs: number | null): void {
        const state = this.origins.get(origin)
        if (state) {
            this.removeReservation(state, reservedStartAtMs)
            state.lastRequestStartedAtMs = nowMs
        }
    }

    public blockedReason(
        origin: string,
        nowMs: number,
        allowHalfOpenProbe = false
    ): Exclude<BudgetBlockReason, 'deadline' | 'origin_map_full'> | null {
        const state = this.origins.get(origin)
        if (!state) {
            return null
        }
        if (state.blockedUntilMs > nowMs || (state.breakerOpen && state.halfOpenProbeInFlight && !allowHalfOpenProbe)) {
            return state.breakerOpen ? 'breaker_open' : 'backoff'
        }
        return null
    }

    public requestStartWaitMs(origin: string, nowMs: number): number {
        const state = this.origins.get(origin)
        return state?.lastRequestStartedAtMs === null || state?.lastRequestStartedAtMs === undefined
            ? 0
            : Math.max(0, state.lastRequestStartedAtMs + state.crawlDelayMs - nowMs)
    }

    public blockedForMs(origin: string, nowMs: number): number {
        const state = this.origins.get(origin)
        if (!state) {
            return 0
        }
        if (state.breakerOpen && state.halfOpenProbeInFlight && state.blockedUntilMs <= nowMs) {
            return this.options.breakerCooldownMs
        }
        return Math.max(0, state.blockedUntilMs - nowMs)
    }

    public returnGrant(origin: string, nowMs: number, reservedStartAtMs: number | null): void {
        const state = this.origins.get(origin)
        if (!state) {
            return
        }
        this.removeReservation(state, reservedStartAtMs)
        this.refill(state, nowMs)
        state.tokens = Math.min(this.options.burst, state.tokens + 1)
        if (state.breakerOpen) {
            state.halfOpenProbeInFlight = false
        }
    }

    public acquireConnection(origin: string, nowMs: number): boolean {
        const state = this.stateFor(origin, nowMs)
        if (!state || state.inFlight >= this.options.maxConcurrent) {
            return false
        }
        state.inFlight += 1
        return true
    }

    public releaseConnection(origin: string): void {
        const state = this.origins.get(origin)
        if (state) {
            state.inFlight = Math.max(0, state.inFlight - 1)
        }
    }

    public configurationRequestStarted(origin: string, nowMs: number): boolean {
        const state = this.stateFor(origin, nowMs)
        if (!state) {
            return false
        }
        state.configurationRequests += 1
        return true
    }

    public configurationRequestFinished(origin: string): void {
        const state = this.origins.get(origin)
        if (state) {
            state.configurationRequests = Math.max(0, state.configurationRequests - 1)
        }
    }

    public setCrawlDelay(origin: string, crawlDelayMs: number, nowMs: number): boolean {
        const state = this.stateFor(origin, nowMs)
        if (!state) {
            return false
        }
        state.crawlDelayMs = Math.max(1_000, crawlDelayMs)
        return true
    }

    public recordTransientFailure(origin: string, nowMs: number, retryAfterMs?: number): number {
        const state = this.stateFor(origin, nowMs)
        if (!state) {
            return this.options.breakerCooldownMs
        }
        state.consecutiveTransientFailures += 1
        const maximumDelayMs = Math.min(
            this.options.breakerCooldownMs * 2 ** (state.consecutiveTransientFailures - 1),
            this.options.breakerMaxCooldownMs
        )
        const minimumDelayMs = Math.ceil(maximumDelayMs / 2)
        const jitteredDelayMs = Math.min(
            maximumDelayMs,
            minimumDelayMs + Math.floor(this.random() * (maximumDelayMs - minimumDelayMs + 1))
        )
        const delayMs = Math.max(jitteredDelayMs, retryAfterMs ?? 0)
        state.blockedUntilMs = Math.max(state.blockedUntilMs, nowMs + delayMs)
        if (state.consecutiveTransientFailures >= this.options.breakerFailures) {
            state.breakerOpen = true
            state.halfOpenProbeInFlight = false
        }
        return delayMs
    }

    public recordCompletedResponse(origin: string, nowMs: number): void {
        const state = this.origins.get(origin)
        if (!state) {
            return
        }
        state.consecutiveTransientFailures = 0
        state.blockedUntilMs = nowMs
        state.breakerOpen = false
        state.halfOpenProbeInFlight = false
    }

    public get trackedDomains(): number {
        return this.origins.size
    }

    public evictedWhileBlocked = 0

    public blockedDomains(nowMs: number): number {
        let blocked = 0
        for (const state of this.origins.values()) {
            if (state.blockedUntilMs > nowMs || state.breakerOpen) {
                blocked += 1
            }
        }
        return blocked
    }

    private refill(state: OriginState, nowMs: number): void {
        const elapsedMs = Math.max(0, nowMs - state.lastRefillMs)
        state.lastRefillMs = nowMs
        state.tokens = Math.min(this.options.burst, state.tokens + (elapsedMs / 1000) * this.options.requestsPerSecond)
    }

    private stateFor(origin: string, nowMs: number): OriginState | undefined {
        const existing = this.origins.get(origin)
        if (existing) {
            this.origins.delete(origin)
            this.origins.set(origin, existing)
            return existing
        }
        if (!this.evictIfFull(nowMs)) {
            return undefined
        }
        const state: OriginState = {
            inFlight: 0,
            configurationRequests: 0,
            tokens: this.options.burst,
            lastRefillMs: nowMs,
            lastRequestStartedAtMs: null,
            reservedStartTimesMs: [],
            crawlDelayMs: 1_000,
            consecutiveTransientFailures: 0,
            blockedUntilMs: 0,
            breakerOpen: false,
            halfOpenProbeInFlight: false,
        }
        this.origins.set(origin, state)
        return state
    }

    private evictIfFull(nowMs: number): boolean {
        if (this.origins.size < this.options.maxTrackedDomains) {
            return true
        }
        for (let scanned = 0; scanned < EVICTION_SCAN_LIMIT; scanned++) {
            const oldest = this.origins.entries().next().value as [string, OriginState] | undefined
            if (!oldest) {
                return true
            }
            const [origin, state] = oldest
            this.refill(state, nowMs)
            const eligible =
                state.inFlight === 0 &&
                state.configurationRequests === 0 &&
                state.reservedStartTimesMs.length === 0 &&
                state.blockedUntilMs <= nowMs &&
                !state.breakerOpen &&
                !state.halfOpenProbeInFlight &&
                state.tokens >= this.options.burst &&
                (state.lastRequestStartedAtMs === null || state.lastRequestStartedAtMs + state.crawlDelayMs <= nowMs)
            if (eligible) {
                this.origins.delete(origin)
                return true
            }
            this.origins.delete(origin)
            this.origins.set(origin, state)
        }
        return false
    }

    private removeReservation(state: OriginState, reservedStartAtMs: number | null): void {
        if (reservedStartAtMs === null) {
            return
        }
        const index = state.reservedStartTimesMs.indexOf(reservedStartAtMs)
        if (index >= 0) {
            state.reservedStartTimesMs.splice(index, 1)
        }
    }
}
