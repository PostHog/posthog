export interface HostBudgetOptions {
    requestsPerSecond: number
    burst: number
    maxConcurrent: number
    breakerFailures: number
    breakerCooldownMs: number
    breakerMaxCooldownMs: number
    maxTrackedRegistrableDomains: number
    maxTrackedOrigins: number
    random?: () => number
}

export type BudgetBlockReason =
    | 'breaker_open'
    | 'backoff'
    | 'deadline'
    | 'origin_map_full'
    | 'registrable_domain_map_full'
export type BudgetWaitScope = 'origin_crawl_delay' | 'registrable_domain_rate'
export type BudgetGrant =
    | {
          granted: true
          waitMs: number
          waitScope: BudgetWaitScope | null
          halfOpenProbe: boolean
          reservedStartAtMs: number | null
      }
    | { granted: false; reason: BudgetBlockReason; waitMs: number }

const EVICTION_SCAN_LIMIT = 64

interface RegistrableDomainState {
    inFlight: number
    pendingGrants: number
    tokens: number
    lastRefillMs: number
    consecutiveTransientFailures: number
    blockedUntilMs: number
    breakerOpen: boolean
    halfOpenProbeInFlight: boolean
}

interface OriginState {
    inFlight: number
    pendingRequests: number
    lastRequestStartedAtMs: number | null
    reservedStartTimesMs: number[]
    crawlDelayMs: number
}

export class HostBudget {
    private readonly registrableDomains = new Map<string, RegistrableDomainState>()
    private readonly origins = new Map<string, OriginState>()
    private readonly random: () => number

    constructor(private readonly options: HostBudgetOptions) {
        for (const [name, value] of Object.entries(options)) {
            if (name !== 'random' && (!Number.isFinite(value) || (value as number) <= 0)) {
                throw new Error(`the image fetch request budget needs a positive ${name}, got ${value}`)
            }
        }
        this.random = options.random ?? Math.random
    }

    public take(
        registrableDomain: string,
        origin: string,
        nowMs: number,
        deadlineMs: number,
        ignoreImageDelay = false
    ): BudgetGrant {
        const registrableDomainState = this.registrableDomainStateFor(registrableDomain, nowMs)
        if (!registrableDomainState) {
            return { granted: false, reason: 'registrable_domain_map_full', waitMs: 0 }
        }
        const originState = this.originStateFor(origin, nowMs)
        if (!originState) {
            return { granted: false, reason: 'origin_map_full', waitMs: 0 }
        }
        let halfOpenProbe = false
        if (!ignoreImageDelay) {
            if (registrableDomainState.blockedUntilMs > nowMs) {
                return {
                    granted: false,
                    reason: registrableDomainState.breakerOpen ? 'breaker_open' : 'backoff',
                    waitMs: registrableDomainState.blockedUntilMs - nowMs,
                }
            }
            if (registrableDomainState.breakerOpen) {
                if (registrableDomainState.halfOpenProbeInFlight) {
                    return { granted: false, reason: 'breaker_open', waitMs: this.options.breakerCooldownMs }
                }
                halfOpenProbe = true
            }
        }
        this.refill(registrableDomainState, nowMs)
        const tokenWaitMs =
            registrableDomainState.tokens >= 1
                ? 0
                : Math.ceil(((1 - registrableDomainState.tokens) / this.options.requestsPerSecond) * 1000)
        const previousStartMs = originState.lastRequestStartedAtMs ?? Number.NEGATIVE_INFINITY
        const crawlWaitMs = ignoreImageDelay ? 0 : Math.max(0, previousStartMs + originState.crawlDelayMs - nowMs)
        const waitMs = Math.max(tokenWaitMs, crawlWaitMs)
        const waitScope: BudgetWaitScope | null =
            waitMs === 0 ? null : crawlWaitMs > tokenWaitMs ? 'origin_crawl_delay' : 'registrable_domain_rate'
        if (nowMs + waitMs > deadlineMs) {
            return { granted: false, reason: 'deadline', waitMs }
        }
        if (waitMs > 0) {
            return {
                granted: true,
                waitMs,
                waitScope,
                halfOpenProbe: false,
                reservedStartAtMs: null,
            }
        }
        if (halfOpenProbe) {
            registrableDomainState.halfOpenProbeInFlight = true
        }
        registrableDomainState.tokens -= 1
        registrableDomainState.pendingGrants += 1
        const reservedStartAtMs = ignoreImageDelay ? null : nowMs
        if (reservedStartAtMs !== null) {
            originState.reservedStartTimesMs.push(reservedStartAtMs)
        }
        return { granted: true, waitMs, waitScope, halfOpenProbe, reservedStartAtMs }
    }

    public markRequestStarted(
        registrableDomain: string,
        origin: string,
        nowMs: number,
        reservedStartAtMs: number | null,
        requestKind: 'configuration' | 'image'
    ): void {
        const registrableDomainState = this.registrableDomains.get(registrableDomain)
        if (registrableDomainState) {
            registrableDomainState.pendingGrants = Math.max(0, registrableDomainState.pendingGrants - 1)
        }
        const originState = this.origins.get(origin)
        if (originState && requestKind === 'image') {
            this.removeReservation(originState, reservedStartAtMs)
            originState.lastRequestStartedAtMs = nowMs
        }
    }

    public blockedForMs(registrableDomain: string, nowMs: number): number {
        const state = this.registrableDomains.get(registrableDomain)
        if (!state) {
            return 0
        }
        if (state.breakerOpen && state.halfOpenProbeInFlight && state.blockedUntilMs <= nowMs) {
            return this.options.breakerCooldownMs
        }
        return Math.max(0, state.blockedUntilMs - nowMs)
    }

    public returnGrant(
        registrableDomain: string,
        origin: string,
        nowMs: number,
        reservedStartAtMs: number | null,
        halfOpenProbe = false
    ): void {
        const originState = this.origins.get(origin)
        if (originState) {
            this.removeReservation(originState, reservedStartAtMs)
        }
        const registrableDomainState = this.registrableDomains.get(registrableDomain)
        if (!registrableDomainState) {
            return
        }
        registrableDomainState.pendingGrants = Math.max(0, registrableDomainState.pendingGrants - 1)
        this.refill(registrableDomainState, nowMs)
        registrableDomainState.tokens = Math.min(this.options.burst, registrableDomainState.tokens + 1)
        if (halfOpenProbe && registrableDomainState.breakerOpen) {
            registrableDomainState.halfOpenProbeInFlight = false
        }
    }

    public acquireConnection(registrableDomain: string, origin: string): boolean {
        const registrableDomainState = this.registrableDomains.get(registrableDomain)
        const originState = this.origins.get(origin)
        if (!registrableDomainState || !originState || registrableDomainState.inFlight >= this.options.maxConcurrent) {
            return false
        }
        registrableDomainState.inFlight += 1
        originState.inFlight += 1
        return true
    }

    public releaseConnection(registrableDomain: string, origin: string): void {
        const registrableDomainState = this.registrableDomains.get(registrableDomain)
        if (registrableDomainState) {
            registrableDomainState.inFlight = Math.max(0, registrableDomainState.inFlight - 1)
        }
        const originState = this.origins.get(origin)
        if (originState) {
            originState.inFlight = Math.max(0, originState.inFlight - 1)
        }
    }

    public requestScheduled(origin: string, nowMs: number): boolean {
        const state = this.originStateFor(origin, nowMs)
        if (!state) {
            return false
        }
        state.pendingRequests += 1
        return true
    }

    public requestFinished(origin: string): void {
        const state = this.origins.get(origin)
        if (state) {
            state.pendingRequests = Math.max(0, state.pendingRequests - 1)
        }
    }

    public setCrawlDelay(origin: string, crawlDelayMs: number, nowMs: number): boolean {
        const state = this.originStateFor(origin, nowMs)
        if (!state) {
            return false
        }
        state.crawlDelayMs = Math.max(1_000, crawlDelayMs)
        return true
    }

    public recordTransientFailure(registrableDomain: string, nowMs: number, retryAfterMs?: number): number {
        const state = this.registrableDomainStateFor(registrableDomain, nowMs)
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

    public recordCompletedResponse(registrableDomain: string, nowMs: number): void {
        const state = this.registrableDomains.get(registrableDomain)
        if (!state) {
            return
        }
        state.consecutiveTransientFailures = 0
        state.blockedUntilMs = Math.max(state.blockedUntilMs, nowMs)
        state.breakerOpen = false
        state.halfOpenProbeInFlight = false
    }

    public get trackedRegistrableDomains(): number {
        return this.registrableDomains.size
    }

    public get trackedOrigins(): number {
        return this.origins.size
    }

    public evictedWhileBlocked = 0

    public blockedRegistrableDomains(nowMs: number): number {
        let blocked = 0
        for (const state of this.registrableDomains.values()) {
            if (state.blockedUntilMs > nowMs || state.breakerOpen) {
                blocked += 1
            }
        }
        return blocked
    }

    private refill(state: RegistrableDomainState, nowMs: number): void {
        const elapsedMs = Math.max(0, nowMs - state.lastRefillMs)
        state.lastRefillMs = nowMs
        state.tokens = Math.min(this.options.burst, state.tokens + (elapsedMs / 1000) * this.options.requestsPerSecond)
    }

    private registrableDomainStateFor(registrableDomain: string, nowMs: number): RegistrableDomainState | undefined {
        const existing = this.registrableDomains.get(registrableDomain)
        if (existing) {
            this.registrableDomains.delete(registrableDomain)
            this.registrableDomains.set(registrableDomain, existing)
            return existing
        }
        if (!this.evictRegistrableDomainIfFull(nowMs)) {
            return undefined
        }
        const state: RegistrableDomainState = {
            inFlight: 0,
            pendingGrants: 0,
            tokens: this.options.burst,
            lastRefillMs: nowMs,
            consecutiveTransientFailures: 0,
            blockedUntilMs: 0,
            breakerOpen: false,
            halfOpenProbeInFlight: false,
        }
        this.registrableDomains.set(registrableDomain, state)
        return state
    }

    private originStateFor(origin: string, nowMs: number): OriginState | undefined {
        const existing = this.origins.get(origin)
        if (existing) {
            this.origins.delete(origin)
            this.origins.set(origin, existing)
            return existing
        }
        if (!this.evictOriginIfFull(nowMs)) {
            return undefined
        }
        const state: OriginState = {
            inFlight: 0,
            pendingRequests: 0,
            lastRequestStartedAtMs: null,
            reservedStartTimesMs: [],
            crawlDelayMs: 1_000,
        }
        this.origins.set(origin, state)
        return state
    }

    private evictRegistrableDomainIfFull(nowMs: number): boolean {
        if (this.registrableDomains.size < this.options.maxTrackedRegistrableDomains) {
            return true
        }
        for (let scanned = 0; scanned < EVICTION_SCAN_LIMIT; scanned++) {
            const oldest = this.registrableDomains.entries().next().value as
                | [string, RegistrableDomainState]
                | undefined
            if (!oldest) {
                return true
            }
            const [registrableDomain, state] = oldest
            this.refill(state, nowMs)
            const eligible =
                state.inFlight === 0 &&
                state.pendingGrants === 0 &&
                state.blockedUntilMs <= nowMs &&
                !state.breakerOpen &&
                !state.halfOpenProbeInFlight &&
                state.tokens >= this.options.burst
            if (eligible) {
                this.registrableDomains.delete(registrableDomain)
                return true
            }
            this.registrableDomains.delete(registrableDomain)
            this.registrableDomains.set(registrableDomain, state)
        }
        return false
    }

    private evictOriginIfFull(nowMs: number): boolean {
        if (this.origins.size < this.options.maxTrackedOrigins) {
            return true
        }
        for (let scanned = 0; scanned < EVICTION_SCAN_LIMIT; scanned++) {
            const oldest = this.origins.entries().next().value as [string, OriginState] | undefined
            if (!oldest) {
                return true
            }
            const [origin, state] = oldest
            const eligible =
                state.inFlight === 0 &&
                state.pendingRequests === 0 &&
                state.reservedStartTimesMs.length === 0 &&
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
