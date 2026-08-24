import { HostBudget, HostBudgetOptions } from './host-budget'

const OPTIONS: HostBudgetOptions = {
    requestsPerSecond: 1,
    burst: 2,
    maxConcurrent: 2,
    breakerFailures: 3,
    breakerCooldownMs: 60_000,
    breakerMaxCooldownMs: 600_000,
    maxTrackedRegistrableDomains: 3,
    maxTrackedOrigins: 3,
    random: () => 1,
}
const DEADLINE_MS = 1_000_000
const REGISTRABLE_DOMAIN = 'example.com'
const ORIGIN = 'https://cdn.example.com'

function budget(overrides: Partial<HostBudgetOptions> = {}): HostBudget {
    return new HostBudget({ ...OPTIONS, ...overrides })
}

describe('HostBudget', () => {
    it('does not reserve a token before a crawl-delay wait finishes', () => {
        const host = budget({ burst: 5 })

        const first = host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)
        expect(first).toEqual({
            granted: true,
            waitMs: 0,
            waitScope: null,
            halfOpenProbe: false,
            reservedStartAtMs: 1_000,
        })
        host.markRequestStarted(
            REGISTRABLE_DOMAIN,
            ORIGIN,
            1_000,
            first.granted ? first.reservedStartAtMs : null,
            'image'
        )
        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)).toEqual({
            granted: true,
            waitMs: 1_000,
            waitScope: 'origin_crawl_delay',
            halfOpenProbe: false,
            reservedStartAtMs: null,
        })
        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)).toEqual({
            granted: true,
            waitMs: 1_000,
            waitScope: 'origin_crawl_delay',
            halfOpenProbe: false,
            reservedStartAtMs: null,
        })
    })

    it('uses the larger robots crawl delay', () => {
        const host = budget({ burst: 5 })
        host.setCrawlDelay(ORIGIN, 4_000, 1_000)

        const first = host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)
        host.markRequestStarted(
            REGISTRABLE_DOMAIN,
            ORIGIN,
            1_000,
            first.granted ? first.reservedStartAtMs : null,
            'image'
        )

        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)).toMatchObject({ waitMs: 4_000 })
    })

    it('keeps crawl delay separate for sibling origins', () => {
        const host = budget({ burst: 5 })
        host.setCrawlDelay('https://a.example.com', 4_000, 1_000)

        host.take(REGISTRABLE_DOMAIN, 'https://a.example.com', 1_000, DEADLINE_MS)

        expect(host.take(REGISTRABLE_DOMAIN, 'https://b.example.com', 1_000, DEADLINE_MS)).toMatchObject({
            granted: true,
            waitMs: 0,
        })
    })

    it('shares token capacity across sibling origins', () => {
        const host = budget({ burst: 1 })

        expect(host.take(REGISTRABLE_DOMAIN, 'https://a.example.com', 1_000, DEADLINE_MS)).toMatchObject({
            granted: true,
            waitMs: 0,
        })
        expect(host.take(REGISTRABLE_DOMAIN, 'https://b.example.com', 1_000, DEADLINE_MS)).toMatchObject({
            granted: true,
            waitMs: 1_000,
        })
    })

    it('returns a token when a reserved request cannot run', () => {
        const host = budget({ burst: 1 })
        const grant = host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)
        expect(grant.granted).toBe(true)
        host.returnGrant(REGISTRABLE_DOMAIN, ORIGIN, 1_000, grant.granted ? grant.reservedStartAtMs : null)

        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)).toMatchObject({ granted: true })
    })

    it('applies half-to-full jitter exponential backoff and Retry-After', () => {
        const host = budget()

        expect(host.recordTransientFailure(REGISTRABLE_DOMAIN, 1_000)).toBe(60_000)
        expect(host.recordTransientFailure(REGISTRABLE_DOMAIN, 1_000, 180_000)).toBe(180_000)
        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, 180_999, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'backoff',
            waitMs: 1,
        })
    })

    it('does not shorten a future block when a concurrent request succeeds', () => {
        const host = budget()
        host.recordTransientFailure(REGISTRABLE_DOMAIN, 1_000, 180_000)
        host.recordCompletedResponse(REGISTRABLE_DOMAIN, 2_000)

        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, 2_000, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'backoff',
            waitMs: 179_000,
        })
    })

    it('opens the breaker after three consecutive transient failures', () => {
        const host = budget()
        for (let failure = 0; failure < OPTIONS.breakerFailures; failure++) {
            host.recordTransientFailure(REGISTRABLE_DOMAIN, 1_000)
        }

        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'breaker_open',
            waitMs: 240_000,
        })
        expect(host.blockedRegistrableDomains(1_000)).toBe(1)
    })

    it('applies a transient failure to sibling origins', () => {
        const host = budget()
        host.recordTransientFailure(REGISTRABLE_DOMAIN, 1_000)

        expect(host.take(REGISTRABLE_DOMAIN, 'https://other.example.com', 1_000, DEADLINE_MS)).toMatchObject({
            granted: false,
            reason: 'backoff',
        })
    })

    it('grants one half-open probe after the breaker cooldown', () => {
        const host = budget()
        for (let failure = 0; failure < OPTIONS.breakerFailures; failure++) {
            host.recordTransientFailure(REGISTRABLE_DOMAIN, 1_000)
        }
        const afterCooldownMs = 1_000 + 240_000

        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, afterCooldownMs, DEADLINE_MS)).toEqual({
            granted: true,
            waitMs: 0,
            waitScope: null,
            halfOpenProbe: true,
            reservedStartAtMs: afterCooldownMs,
        })
        expect(host.take(REGISTRABLE_DOMAIN, 'https://other.example.com', afterCooldownMs, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'breaker_open',
            waitMs: OPTIONS.breakerCooldownMs,
        })
    })

    it('closes the breaker after the half-open probe gets a response', () => {
        const host = budget()
        for (let failure = 0; failure < OPTIONS.breakerFailures; failure++) {
            host.recordTransientFailure(REGISTRABLE_DOMAIN, 1_000)
        }
        const afterCooldownMs = 1_000 + 240_000
        host.take(REGISTRABLE_DOMAIN, ORIGIN, afterCooldownMs, DEADLINE_MS)
        host.recordCompletedResponse(REGISTRABLE_DOMAIN, afterCooldownMs)

        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, afterCooldownMs, DEADLINE_MS)).toMatchObject({ granted: true })
    })

    it('limits concurrent connections across sibling origins', () => {
        const host = budget()
        const origins = ['https://a.example.com', 'https://b.example.com', 'https://c.example.com']
        for (const origin of origins) {
            host.take(REGISTRABLE_DOMAIN, origin, 1_000, DEADLINE_MS)
        }

        expect(host.acquireConnection(REGISTRABLE_DOMAIN, origins[0])).toBe(true)
        expect(host.acquireConnection(REGISTRABLE_DOMAIN, origins[1])).toBe(true)
        expect(host.acquireConnection(REGISTRABLE_DOMAIN, origins[2])).toBe(false)
        host.releaseConnection(REGISTRABLE_DOMAIN, origins[0])
        expect(host.acquireConnection(REGISTRABLE_DOMAIN, origins[2])).toBe(true)
    })

    it('does not evict an origin with a connection or scheduled request', () => {
        const host = budget({ maxTrackedRegistrableDomains: 2, maxTrackedOrigins: 2, maxConcurrent: 1 })
        host.take('busy.example', 'https://busy.example', 1_000, DEADLINE_MS)
        host.acquireConnection('busy.example', 'https://busy.example')
        host.requestScheduled('https://config.example', 1_000)
        host.take('config.example', 'https://config.example', 1_000, DEADLINE_MS, true)

        expect(host.take('new.example', 'https://new.example', 1_000, DEADLINE_MS)).toEqual({
            granted: false,
            reason: 'registrable_domain_map_full',
            waitMs: 0,
        })
        expect(host.acquireConnection('busy.example', 'https://busy.example')).toBe(false)
    })

    it('evicts an idle full-budget origin', () => {
        const host = budget({ maxTrackedRegistrableDomains: 1, maxTrackedOrigins: 1 })
        const grant = host.take('idle.example', 'https://idle.example', 1_000, DEADLINE_MS)
        expect(grant.granted).toBe(true)
        host.returnGrant('idle.example', 'https://idle.example', 1_000, grant.granted ? grant.reservedStartAtMs : null)

        expect(host.take('new.example', 'https://new.example', 1_000, DEADLINE_MS)).toMatchObject({ granted: true })
        expect(host.trackedRegistrableDomains).toBe(1)
        expect(host.trackedOrigins).toBe(1)
    })

    it('returns a crawl wait that extends beyond the pass deadline', () => {
        const host = budget({ burst: 5 })
        host.setCrawlDelay(ORIGIN, 600_000, 1_000)
        const first = host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, DEADLINE_MS)
        host.markRequestStarted(
            REGISTRABLE_DOMAIN,
            ORIGIN,
            1_000,
            first.granted ? first.reservedStartAtMs : null,
            'image'
        )

        expect(host.take(REGISTRABLE_DOMAIN, ORIGIN, 1_000, 20_000)).toEqual({
            granted: false,
            reason: 'deadline',
            waitMs: 600_000,
        })
    })
})
