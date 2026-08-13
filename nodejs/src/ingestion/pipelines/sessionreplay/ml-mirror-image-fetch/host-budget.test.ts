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

        // The two burst tokens go out together; each one after them waits a whole second, because
        // the token that would carry it has not been earned yet.
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

        // Granting here would spend a token for a request the caller cannot send, and the next
        // batch would then wait that token out for nothing.
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
        host.take('example.com', 1000, FAR_FUTURE)
        // 2 requests per second after the halving, so the next token is 500ms out rather than 250ms.
        expect(host.take('example.com', 1000, FAR_FUTURE)).toEqual({ granted: true, waitMs: 500 })

        for (let i = 0; i < 20; i++) {
            host.recordSuccess('example.com', 1000)
        }
        host.take('example.com', 20_000, FAR_FUTURE)
        expect(host.take('example.com', 20_000, FAR_FUTURE)).toEqual({ granted: true, waitMs: 250 })
    })

    it('does not shorten a Retry-After hold when the breaker opens inside it', () => {
        const host = budget()
        const anHourMs = 60 * 60 * 1000
        host.recordRetryAfter('example.com', 1000, anHourMs)

        for (let i = 0; i < OPTIONS.breakerFailures; i++) {
            host.recordBackoff('example.com', 1000)
        }

        // The breaker cooldown is one minute. Letting it replace the hold would send us back to a
        // site that asked for an hour, 59 minutes early.
        expect(host.take('example.com', 1000 + OPTIONS.breakerCooldownMs + 1, FAR_FUTURE)).toEqual({
            granted: false,
            reason: 'rate_limited',
        })
    })

    it('holds one domain to its connection limit however many callers ask', () => {
        // The runner's worker pool bounds only the domain a URL was queued under. A redirect reaches
        // a domain from another domain's worker, so the limit has to live here to bind at all.
        const host = budget({ maxConcurrent: 2 })

        expect(host.acquireConnection('example.com', 1000)).toBe(true)
        expect(host.acquireConnection('example.com', 1000)).toBe(true)
        expect(host.acquireConnection('example.com', 1000)).toBe(false)

        host.releaseConnection('example.com')

        expect(host.acquireConnection('example.com', 1000)).toBe(true)
    })

    it('keeps a domain holding a connection out of the eviction scan', () => {
        // Evicting it would drop the in-flight count, and the next caller would open one more
        // connection than the limit allows.
        const host = budget({ maxTrackedDomains: 2, maxConcurrent: 1 })
        host.acquireConnection('busy.com', 1000)
        host.take('idle.com', 1000, FAR_FUTURE)

        host.take('new.com', 1000, FAR_FUTURE)

        expect(host.acquireConnection('busy.com', 1000)).toBe(false)
    })

    it('opens the breaker on a domain that fails more often than it succeeds', () => {
        // Two failures for every success never makes a run of failures, so a counter that cleared
        // on success would leave a mostly-broken domain being retried forever.
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

        // The reason is what the shed outcome and the metric carry. Letting the shorter hold rename
        // it would hide the breaker from the one number that exists to show it.
        expect(host.take('example.com', 2000, FAR_FUTURE)).toEqual({ granted: false, reason: 'breaker_open' })
    })

    it('does not report a busy but unblocked domain as one whose hold it forgot', () => {
        // The eviction scan skips a domain that is blocked or that has connections open. Only the
        // first kind loses a hold, and the metric is named for that kind.
        const host = budget({ maxTrackedDomains: 1, maxConcurrent: 1 })
        host.acquireConnection('busy.com', 1000)

        host.take('new.com', 1000, FAR_FUTURE)

        expect(host.evictedWhileBlocked).toBe(0)
    })

    it('evicts an idle domain in preference to one it is still holding back', () => {
        const host = budget({ maxTrackedDomains: 2 })
        host.recordRetryAfter('blocked.com', 1000, 60_000)
        host.take('idle.com', 1000, FAR_FUTURE)

        host.take('new.com', 1000, FAR_FUTURE)

        expect(host.trackedDomains).toBe(2)
        // Evicting the blocked domain would forget that a site asked us to wait, so the idle one goes.
        expect(host.take('blocked.com', 1000, FAR_FUTURE)).toEqual({ granted: false, reason: 'rate_limited' })
    })
})
