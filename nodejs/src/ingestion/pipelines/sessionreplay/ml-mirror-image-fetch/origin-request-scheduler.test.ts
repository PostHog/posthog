import { HostBudget, HostBudgetOptions } from './host-budget'
import { OriginRequestScheduler } from './origin-request-scheduler'

const OPTIONS: HostBudgetOptions = {
    requestsPerSecond: 1,
    burst: 5,
    maxConcurrent: 6,
    breakerFailures: 2,
    breakerCooldownMs: 60_000,
    breakerMaxCooldownMs: 3_600_000,
    maxTrackedDomains: 20_000,
    random: () => 1,
}
const ORIGIN = 'https://example.com'

describe('OriginRequestScheduler', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(1_700_000_000_000))
    afterEach(() => jest.useRealTimers())

    it('keeps concurrent request start times at least one second apart', async () => {
        const scheduler = new OriginRequestScheduler(new HostBudget(OPTIONS), 300)
        const startedAtMs: number[] = []
        const deadlineMs = Date.now() + 10_000

        const requests = [0, 1, 2].map(() =>
            scheduler.runImage(ORIGIN, deadlineMs, () => {
                startedAtMs.push(Date.now())
                return Promise.resolve()
            })
        )
        await jest.runAllTimersAsync()

        expect(await Promise.all(requests)).toEqual([
            { ran: true, value: undefined },
            { ran: true, value: undefined },
            { ran: true, value: undefined },
        ])
        expect(startedAtMs).toEqual([1_700_000_000_000, 1_700_000_001_000, 1_700_000_002_000])
    })

    it('runs one half-open probe while later requests remain blocked', async () => {
        const budget = new HostBudget(OPTIONS)
        budget.recordTransientFailure(ORIGIN, Date.now())
        budget.recordTransientFailure(ORIGIN, Date.now())
        jest.setSystemTime(Date.now() + 120_001)
        const scheduler = new OriginRequestScheduler(budget, 300)
        let finishProbe: (() => void) | undefined
        const probe = scheduler.runImage(
            ORIGIN,
            Date.now() + 10_000,
            () =>
                new Promise<void>((resolve) => {
                    finishProbe = resolve
                })
        )

        await Promise.resolve()
        await expect(scheduler.runImage(ORIGIN, Date.now() + 10_000, () => Promise.resolve())).resolves.toEqual({
            ran: false,
            reason: 'breaker_open',
            waitMs: OPTIONS.breakerCooldownMs,
        })
        expect(finishProbe).toBeDefined()
        finishProbe?.()
        await expect(probe).resolves.toEqual({ ran: true, value: undefined })
    })

    it('returns a queued request to the caller when its pass deadline expires', async () => {
        const scheduler = new OriginRequestScheduler(new HostBudget(OPTIONS), 1)
        let releaseFirst: (() => void) | undefined
        const first = scheduler.runImage(
            'https://first.example',
            Date.now() + 10_000,
            () =>
                new Promise<void>((resolve) => {
                    releaseFirst = resolve
                })
        )
        const second = scheduler.runImage('https://second.example', Date.now() + 500, () => Promise.resolve())

        await Promise.resolve()
        jest.advanceTimersByTime(501)
        releaseFirst?.()

        await expect(first).resolves.toEqual({ ran: true, value: undefined })
        await expect(second).resolves.toEqual({ ran: false, reason: 'deadline', waitMs: 0 })
    })

    it('returns a crawl wait that is longer than the pass deadline', async () => {
        const budget = new HostBudget(OPTIONS)
        budget.setCrawlDelay(ORIGIN, 600_000, Date.now())
        const scheduler = new OriginRequestScheduler(budget, 300)
        await expect(scheduler.runImage(ORIGIN, Date.now() + 10_000, () => Promise.resolve())).resolves.toMatchObject({
            ran: true,
        })

        await expect(scheduler.runImage(ORIGIN, Date.now() + 20_000, () => Promise.resolve())).resolves.toEqual({
            ran: false,
            reason: 'deadline',
            waitMs: 600_000,
        })
    })
})
