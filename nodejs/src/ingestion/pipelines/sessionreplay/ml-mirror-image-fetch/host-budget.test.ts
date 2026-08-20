import { HostBudget, HostBudgetOptions } from './host-budget'

const OPTIONS: HostBudgetOptions = {
    requestsPerSecond: 1,
    burst: 2,
    maxConcurrent: 4,
    breakerFailures: 3,
    breakerCooldownMs: 60_000,
    breakerMaxCooldownMs: 600_000,
    maxTrackedDomains: 3,
}

function budget(overrides: Partial<HostBudgetOptions> = {}): HostBudget {
    return new HostBudget({ ...OPTIONS, ...overrides })
}

const FAR_FUTURE = 10 ** 12

describe('HostBudget', () => {
    it('spends the burst at once and then paces at the configured rate', () => {
        const host = budget()

        const grants = [0, 0, 0, 0].map(() => host.take('example.com', 1000, FAR_FUTURE))

        expect(grants).toEqual([
            { granted: true, waitMs: 0 },
            { granted: true, waitMs: 0 },
            { granted: true, waitMs: 1000 },
            { granted: true, waitMs: 2000 },
        ])
    })

    it('refuses rather than granting a slot that lands after the deadline', () => {
        const host = budget()
        host.take('example.com', 1000, FAR_FUTURE)
        host.take('example.com', 1000, FAR_FUTURE)

        // A grant here spends a token for a request the caller cannot send, and the next batch then
        // waits that token out for nothing.
        expect(host.take('example.com', 1000, 1500)).toEqual({ granted: false, reason: 'deadline' })
        expect(host.take('example.com', 1000, FAR_FUTURE)).toEqual({ granted: true, waitMs: 1000 })
    })

    it('opens the breaker on consecutive failures and closes it when the cooldown passes', () => {
        const host = budget()

        for (let i = 0; i < OPTIONS.breakerFailures; i++) {
            host.recordBackoff('example.com', 1000)
        }

        expect(host.take('example.com', 1000, FAR_FUTURE)).toEqual({ granted: false, reason: 'breaker_open' })
        expect(host.blockedDomains(1000)).toBe(1)
        expect(host.take('example.com', 1000 + OPTIONS.breakerCooldownMs + 1, FAR_FUTURE)).toMatchObject({
            granted: true,
        })
    })

    it('doubles the cooldown for a domain that fails again after the breaker closed', () => {
        const host = budget()
        const openBreaker = (atMs: number): void => {
            for (let i = 0; i < OPTIONS.breakerFailures; i++) {
                host.recordBackoff('example.com', atMs)
            }
        }

        openBreaker(1000)
        const reopenedAt = 1000 + OPTIONS.breakerCooldownMs + 1
        openBreaker(reopenedAt)

        // Still blocked one cooldown later, because the second cooldown is twice the first.
        expect(host.take('example.com', reopenedAt + OPTIONS.breakerCooldownMs + 1, FAR_FUTURE)).toEqual({
            granted: false,
            reason: 'breaker_open',
        })
    })

    it.each([
        ['a period the site named', 30_000, 30_000],
        ['a period longer than the cap', 24 * 60 * 60 * 1000, OPTIONS.breakerMaxCooldownMs],
    ])('holds the domain for %s', (_name, retryAfterMs, expectedHoldMs) => {
        const host = budget()

        host.recordRetryAfter('example.com', 1000, retryAfterMs)

        expect(host.take('example.com', 1000 + expectedHoldMs - 1, FAR_FUTURE)).toEqual({
            granted: false,
            reason: 'rate_limited',
        })
        expect(host.take('example.com', 1000 + expectedHoldMs + 1, FAR_FUTURE)).toMatchObject({ granted: true })
    })

    it('halves the rate on a backoff and never raises it above the configured one', () => {
        const host = budget({ requestsPerSecond: 4, burst: 1 })

        host.recordBackoff('example.com', 1000)
        // The burst went with the halving, so even the first request waits. At 2 per second rather
        // than 4, that wait is 500ms. Requirement 16.
        expect(host.take('example.com', 1000, FAR_FUTURE)).toEqual({ granted: true, waitMs: 500 })
        expect(host.take('example.com', 1000, FAR_FUTURE)).toEqual({ granted: true, waitMs: 1000 })

        for (let i = 0; i < 20; i++) {
            host.recordSuccess('example.com', 1000)
        }
        host.take('example.com', 20_000, FAR_FUTURE)
        expect(host.take('example.com', 20_000, FAR_FUTURE)).toEqual({ granted: true, waitMs: 250 })
    })

    it('makes one failure reach the URLs already queued for the domain (requirement 16)', () => {
        // Without this a site that just failed still receives the whole burst, and the cut reaches
        // only the URLs behind them.
        const host = budget({ requestsPerSecond: 1, burst: 5 })

        expect(host.take('example.com', 1000, FAR_FUTURE)).toEqual({ granted: true, waitMs: 0 })
        host.recordBackoff('example.com', 1000)

        expect(host.take('example.com', 1000, FAR_FUTURE)).toMatchObject({ granted: true, waitMs: 2000 })
    })

    it('does not shorten a Retry-After hold when the breaker opens inside it', () => {
        const host = budget()
        const anHourMs = 60 * 60 * 1000
        host.recordRetryAfter('example.com', 1000, anHourMs)

        for (let i = 0; i < OPTIONS.breakerFailures; i++) {
            host.recordBackoff('example.com', 1000)
        }

        // The breaker cooldown is one minute. A cooldown that replaces the hold sends us back to a
        // site that asked for an hour, 59 minutes early.
        expect(host.take('example.com', 1000 + OPTIONS.breakerCooldownMs + 1, FAR_FUTURE)).toEqual({
            granted: false,
            reason: 'rate_limited',
        })
    })

    it('holds one domain to its connection limit however many callers ask', () => {
        const host = budget({ maxConcurrent: 2 })

        expect(host.acquireConnection('example.com', 1000)).toBe(true)
        expect(host.acquireConnection('example.com', 1000)).toBe(true)
        expect(host.acquireConnection('example.com', 1000)).toBe(false)

        host.releaseConnection('example.com')

        expect(host.acquireConnection('example.com', 1000)).toBe(true)
    })

    it('keeps a domain holding a connection out of the eviction scan', () => {
        // An eviction drops the in-flight count, and the next caller then opens one more connection
        // than the limit allows.
        const host = budget({ maxTrackedDomains: 2, maxConcurrent: 1 })
        host.acquireConnection('busy.com', 1000)
        host.take('idle.com', 1000, FAR_FUTURE)

        host.take('new.com', 1000, FAR_FUTURE)

        expect(host.acquireConnection('busy.com', 1000)).toBe(false)
    })

    it('opens the breaker on a domain that fails more often than it succeeds', () => {
        // Two failures for every success never make a run of failures, so a counter that cleared on
        // success leaves a mostly broken domain in retry forever.
        const host = budget()

        for (let round = 0; round < 5; round++) {
            host.recordBackoff('flapping.com', 1000)
            host.recordBackoff('flapping.com', 1000)
            host.recordSuccess('flapping.com', 1000)
        }

        expect(host.take('flapping.com', 1000, FAR_FUTURE)).toEqual({ granted: false, reason: 'breaker_open' })
    })

    it('keeps reporting an open breaker when a shorter rate-limit hold arrives inside it', () => {
        const host = budget()
        for (let i = 0; i < OPTIONS.breakerFailures; i++) {
            host.recordBackoff('example.com', 1000)
        }

        host.recordRetryAfter('example.com', 1000, 1_000)

        // The shed outcome and the metric carry this reason. A rename by the shorter hold hides the
        // breaker from the one number that exists to show it.
        expect(host.take('example.com', 2000, FAR_FUTURE)).toEqual({ granted: false, reason: 'breaker_open' })
    })

    it('does not report a busy but unblocked domain as one whose hold it forgot', () => {
        // The eviction scan skips a domain that is blocked or that has connections open. Only the
        // first kind loses a hold, and the metric carries the name of that kind.
        const host = budget({ maxTrackedDomains: 1, maxConcurrent: 1 })
        host.acquireConnection('busy.com', 1000)

        host.take('new.com', 1000, FAR_FUTURE)

        expect(host.evictedWhileBlocked).toBe(0)
    })

    it('never evicts a domain holding connections, so its slots are not leaked', () => {
        // A slot is released by domain name. A lost entry leaks every slot it held, and the domain
        // can then hold more than its limit for the rest of the pod's life.
        const host = budget({ maxTrackedDomains: 2, maxConcurrent: 1 })
        expect(host.acquireConnection('busy.com', 1000)).toBe(true)

        host.take('a.com', 1000, FAR_FUTURE)
        host.take('b.com', 1000, FAR_FUTURE)

        // Its entry survived the eviction, so it is still at its limit. A dropped entry would come
        // back with no connections counted and let this domain hold a second one.
        expect(host.acquireConnection('busy.com', 1000)).toBe(false)
    })

    it('evicts an idle domain in preference to one it is still holding back', () => {
        const host = budget({ maxTrackedDomains: 2 })
        host.recordRetryAfter('blocked.com', 1000, 60_000)
        host.take('idle.com', 1000, FAR_FUTURE)

        host.take('new.com', 1000, FAR_FUTURE)

        expect(host.trackedDomains).toBe(2)
        expect(host.take('blocked.com', 1000, FAR_FUTURE)).toEqual({ granted: false, reason: 'rate_limited' })
    })
})
