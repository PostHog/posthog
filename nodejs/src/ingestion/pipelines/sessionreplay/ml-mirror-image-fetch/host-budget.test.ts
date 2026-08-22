import { HostBudget, HostBudgetOptions } from './host-budget'

const OPTIONS: HostBudgetOptions = {
    requestsPerSecond: 1,
    burst: 2,
    maxConcurrent: 2,
    breakerFailures: 3,
    breakerCooldownMs: 60_000,
    breakerMaxCooldownMs: 600_000,
    maxTrackedDomains: 3,
    random: () => 1,
}
const DEADLINE_MS = 1_000_000

function budget(overrides: Partial<HostBudgetOptions> = {}): HostBudget {
    return new HostBudget({ ...OPTIONS, ...overrides })
}

describe('HostBudget', () => {
    it('reserves token and crawl-delay starts across concurrent callers', () => {
        const host = budget({ burst: 5 })

        expect(host.take('https://example.com', 1_000, DEADLINE_MS)).toEqual({
            granted: true,
            waitMs: 0,
            halfOpenProbe: false,
            reservedStartAtMs: 1_000,
        })
        expect(host.take('https://example.com', 1_000, DEADLINE_MS)).toEqual({
            granted: true,
            waitMs: 1_000,
            halfOpenProbe: false,
            reservedStartAtMs: 2_000,
        })
        expect(host.take('https://example.com', 1_000, DEADLINE_MS)).toEqual({
            granted: true,
            waitMs: 2_000,
            halfOpenProbe: false,
            reservedStartAtMs: 3_000,
        })
    })

    it('uses the larger robots crawl delay', () => {
        const host = budget({ burst: 5 })
        host.setCrawlDelay('https://example.com', 4_000, 1_000)

        host.take('https://example.com', 1_000, DEADLINE_MS)

        expect(host.take('https://example.com', 1_000, DEADLINE_MS)).toMatchObject({ waitMs: 4_000 })
    })

    it('returns a token when a reserved request cannot run', () => {
        const host = budget({ burst: 1 })
        const grant = host.take('https://example.com', 1_000, DEADLINE_MS)
        expect(grant.granted).toBe(true)
        host.returnGrant('https://example.com', 1_000, grant.granted ? grant.reservedStartAtMs : null)

        expect(host.take('https://example.com', 1_000, DEADLINE_MS)).toMatchObject({ granted: true })
    })

    it('applies half-to-full jitter exponential backoff and Retry-After', () => {
        const host = budget()

        expect(host.recordTransientFailure('https://example.com', 1_000)).toBe(60_000)
        expect(host.recordTransientFailure('https://example.com', 1_000, 180_000)).toBe(180_000)
        expect(host.take('https://example.com', 180_999, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'backoff',
            waitMs: 1,
        })
    })

    it('opens the breaker after three consecutive transient failures', () => {
        const host = budget()
        for (let failure = 0; failure < OPTIONS.breakerFailures; failure++) {
            host.recordTransientFailure('https://example.com', 1_000)
        }

        expect(host.take('https://example.com', 1_000, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'breaker_open',
            waitMs: 240_000,
        })
        expect(host.blockedDomains(1_000)).toBe(1)
    })

    it('grants one half-open probe after the breaker cooldown', () => {
        const host = budget()
        for (let failure = 0; failure < OPTIONS.breakerFailures; failure++) {
            host.recordTransientFailure('https://example.com', 1_000)
        }
        const afterCooldownMs = 1_000 + 240_000

        expect(host.take('https://example.com', afterCooldownMs, DEADLINE_MS)).toEqual({
            granted: true,
            waitMs: 0,
            halfOpenProbe: true,
            reservedStartAtMs: afterCooldownMs,
        })
        expect(host.take('https://example.com', afterCooldownMs, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'breaker_open',
            waitMs: OPTIONS.breakerCooldownMs,
        })
    })

    it('closes the breaker after the half-open probe gets a response', () => {
        const host = budget()
        for (let failure = 0; failure < OPTIONS.breakerFailures; failure++) {
            host.recordTransientFailure('https://example.com', 1_000)
        }
        const afterCooldownMs = 1_000 + 240_000
        host.take('https://example.com', afterCooldownMs, DEADLINE_MS)
        host.recordCompletedResponse('https://example.com', afterCooldownMs)

        expect(host.take('https://example.com', afterCooldownMs, DEADLINE_MS)).toMatchObject({ granted: true })
    })

    it('limits concurrent connections for one origin', () => {
        const host = budget()

        expect(host.acquireConnection('https://example.com', 1_000)).toBe(true)
        expect(host.acquireConnection('https://example.com', 1_000)).toBe(true)
        expect(host.acquireConnection('https://example.com', 1_000)).toBe(false)
        host.releaseConnection('https://example.com')
        expect(host.acquireConnection('https://example.com', 1_000)).toBe(true)
    })

    it('does not evict an origin with a connection or configuration request', () => {
        const host = budget({ maxTrackedDomains: 2, maxConcurrent: 1 })
        host.acquireConnection('https://busy.example', 1_000)
        host.configurationRequestStarted('https://config.example', 1_000)

        expect(host.take('https://new.example', 1_000, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'origin_map_full',
            waitMs: 0,
        })
        expect(host.acquireConnection('https://busy.example', 1_000)).toBe(false)
    })

    it('evicts an idle full-budget origin', () => {
        const host = budget({ maxTrackedDomains: 1 })
        const grant = host.take('https://idle.example', 1_000, DEADLINE_MS)
        expect(grant.granted).toBe(true)
        host.returnGrant('https://idle.example', 1_000, grant.granted ? grant.reservedStartAtMs : null)

        expect(host.take('https://new.example', 1_000, DEADLINE_MS)).toMatchObject({ granted: true })
        expect(host.trackedDomains).toBe(1)
    })

    it('returns a crawl wait that extends beyond the pass deadline', () => {
        const host = budget({ burst: 5 })
        host.setCrawlDelay('https://example.com', 600_000, 1_000)
        host.take('https://example.com', 1_000, DEADLINE_MS)

        expect(host.take('https://example.com', 1_000, 20_000)).toEqual({
            granted: false,
            reason: 'deadline',
            waitMs: 600_000,
        })
    })
})
