import { HostBudget, HostBudgetOptions } from './host-budget'
import { ImageFetchRequestMetrics } from './metrics'
import { OriginRequestScheduler } from './origin-request-scheduler'

const OPTIONS: HostBudgetOptions = {
    requestsPerSecond: 1,
    burst: 5,
    maxConcurrent: 6,
    breakerFailures: 2,
    breakerCooldownMs: 60_000,
    breakerMaxCooldownMs: 3_600_000,
    maxTrackedRegistrableDomains: 20_000,
    maxTrackedOrigins: 20_000,
    random: () => 1,
}
const ORIGIN = new URL('https://example.com')
const REGISTRABLE_DOMAIN = 'example.com'

describe('OriginRequestScheduler', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(1_700_000_000_000))
    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('keeps concurrent request start times at least one second apart', async () => {
        const budget = new HostBudget(OPTIONS)
        budget.setCrawlDelay(ORIGIN.origin, 1_000, Date.now())
        const scheduler = new OriginRequestScheduler(budget, 300)
        const observeSchedulerWait = jest.spyOn(ImageFetchRequestMetrics, 'observeSchedulerWait')
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
        expect(observeSchedulerWait).toHaveBeenCalledWith('origin_crawl_delay', 1)
        expect(observeSchedulerWait).toHaveBeenCalledWith('request_capacity', 0)
    })

    it('allows six concurrent same-origin requests when the request rate and crawl delay are disabled', async () => {
        const scheduler = new OriginRequestScheduler(
            new HostBudget({ ...OPTIONS, requestsPerSecond: 0, burst: 6, maxConcurrent: 6 }),
            300
        )
        const releases: Array<() => void> = []
        const requests = Array.from({ length: 7 }, () =>
            scheduler.runImage(
                ORIGIN,
                Date.now() + 10_000,
                () =>
                    new Promise<void>((resolve) => {
                        releases.push(resolve)
                    })
            )
        )

        await expect(requests[6]).resolves.toEqual({ ran: false, reason: 'connection_limit', waitMs: 0 })
        expect(releases).toHaveLength(6)
        releases.forEach((release) => release())
        await expect(Promise.all(requests.slice(0, 6))).resolves.toEqual(
            Array.from({ length: 6 }, () => ({ ran: true, value: undefined }))
        )
    })

    it('runs one half-open probe while later requests remain blocked', async () => {
        const budget = new HostBudget(OPTIONS)
        budget.recordTransientFailure(REGISTRABLE_DOMAIN, Date.now())
        budget.recordTransientFailure(REGISTRABLE_DOMAIN, Date.now())
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
            new URL('https://first.example'),
            Date.now() + 10_000,
            () =>
                new Promise<void>((resolve) => {
                    releaseFirst = resolve
                })
        )
        const second = scheduler.runImage(new URL('https://second.example'), Date.now() + 500, () => Promise.resolve())

        await Promise.resolve()
        jest.advanceTimersByTime(501)
        releaseFirst?.()

        await expect(first).resolves.toEqual({ ran: true, value: undefined })
        await expect(second).resolves.toEqual({ ran: false, reason: 'deadline', waitMs: 0 })
    })

    it('checks the registrable-domain token bucket after a pod-capacity wait', async () => {
        const scheduler = new OriginRequestScheduler(new HostBudget({ ...OPTIONS, burst: 2 }), 1)
        const startedAtMs: number[] = []
        let releaseFirst: (() => void) | undefined
        const startRequest = (origin: string, hold = false): Promise<unknown> =>
            scheduler.runImage(new URL(origin), Date.now() + 30_000, () => {
                startedAtMs.push(Date.now())
                if (!hold) {
                    return Promise.resolve()
                }
                return new Promise<void>((resolve) => {
                    releaseFirst = resolve
                })
            })

        const requests = [
            startRequest('https://a.example.com/image.png', true),
            startRequest('https://b.example.com/image.png'),
            startRequest('https://c.example.com/image.png'),
            startRequest('https://d.example.com/image.png'),
        ]
        await Promise.resolve()
        jest.advanceTimersByTime(10_000)
        releaseFirst?.()
        await jest.runAllTimersAsync()
        await Promise.all(requests)

        expect(startedAtMs).toEqual([1_700_000_000_000, 1_700_000_010_000, 1_700_000_010_000, 1_700_000_011_000])
    })

    it('returns a crawl wait that is longer than the pass deadline', async () => {
        const budget = new HostBudget(OPTIONS)
        budget.setCrawlDelay(ORIGIN.origin, 600_000, Date.now())
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

    it('shares the connection limit across sibling origins', async () => {
        const scheduler = new OriginRequestScheduler(new HostBudget({ ...OPTIONS, maxConcurrent: 1 }), 300)
        let releaseFirst: (() => void) | undefined
        const first = scheduler.runImage(
            new URL('https://a.example.com/image.png'),
            Date.now() + 10_000,
            () =>
                new Promise<void>((resolve) => {
                    releaseFirst = resolve
                })
        )

        await Promise.resolve()
        await expect(
            scheduler.runImage(new URL('https://b.example.com/image.png'), Date.now() + 10_000, () => Promise.resolve())
        ).resolves.toEqual({ ran: false, reason: 'connection_limit', waitMs: 0 })

        releaseFirst?.()
        await expect(first).resolves.toEqual({ ran: true, value: undefined })
    })

    it('counts a configuration request against the registrable-domain connection limit', async () => {
        const scheduler = new OriginRequestScheduler(new HostBudget({ ...OPTIONS, maxConcurrent: 1 }), 300)
        let releaseConfiguration: (() => void) | undefined
        const configuration = scheduler.run(
            new URL('https://a.example.com/robots.txt'),
            Date.now() + 10_000,
            () =>
                new Promise<void>((resolve) => {
                    releaseConfiguration = resolve
                })
        )

        await Promise.resolve()
        await expect(
            scheduler.runImage(new URL('https://b.example.com/image.png'), Date.now() + 10_000, () => Promise.resolve())
        ).resolves.toEqual({ ran: false, reason: 'connection_limit', waitMs: 0 })

        expect(releaseConfiguration).toBeDefined()
        releaseConfiguration?.()
        await expect(configuration).resolves.toEqual({ ran: true, value: undefined })
    })
})
