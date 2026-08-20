import { delay } from '~/common/utils/utils'

import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { FetchRunner, FetchRunnerOptions, isTerminal } from './fetch-runner'
import { FrontierPublisher } from './frontier-publisher'
import { HostBudget } from './host-budget'
import { FetchOutcome, ImageFetchResult, ImageFetcher, RedirectDecision } from './image-fetcher'

const OPTIONS: FetchRunnerOptions = {
    maxConcurrentPerDomain: 2,
    maxInFlightRequests: 50,
    batchBudgetMs: 5000,
    maxBytes: 1000,
    requestTimeoutMs: 1000,
    maxRedirects: 3,
    defaultRetryAfterMs: 60_000,
}

function candidate(domain: string, index: number): FetchCandidate {
    return {
        ref: `imageurl:team:${domain}-${index}`,
        urlHash: `${domain}-${index}`,
        url: `https://cdn.${domain}/${index}.png`,
        host: `cdn.${domain}`,
        domain,
        pseudoTeam: 'team',
        capturedAtMs: 1000,
        hopsRemaining: MAX_HOPS,
        notBeforeMs: 0,
    }
}

class FakeFetcher implements ImageFetcher {
    public calls: string[] = []
    public peakConcurrent = 0
    private inFlight = 0

    constructor(private readonly answer: (url: string) => Partial<ImageFetchResult>) {}

    public async fetch(url: string): Promise<ImageFetchResult> {
        this.calls.push(url)
        this.inFlight++
        this.peakConcurrent = Math.max(this.peakConcurrent, this.inFlight)
        await Promise.resolve()
        this.inFlight--
        return { outcome: 'ok', redirects: 0, ...this.answer(url) }
    }
}

const FAR_FUTURE = 10 ** 12

const defaultBudget = (): HostBudget =>
    new HostBudget({
        requestsPerSecond: 1000,
        burst: 1000,
        maxConcurrent: 4,
        breakerFailures: 3,
        breakerCooldownMs: 60_000,
        breakerMaxCooldownMs: 600_000,
        maxTrackedDomains: 100,
    })

function runner(
    fetcher: ImageFetcher,
    options: Partial<FetchRunnerOptions> = {},
    budget = new HostBudget({
        requestsPerSecond: 1000,
        burst: 1000,
        maxConcurrent: 4,
        breakerFailures: 3,
        breakerCooldownMs: 60_000,
        breakerMaxCooldownMs: 600_000,
        maxTrackedDomains: 100,
    }),
    publisher: FrontierPublisher = noopPublisher()
): FetchRunner {
    return new FetchRunner(fetcher, budget, { ...OPTIONS, ...options }, publisher)
}

function noopPublisher(): FrontierPublisher {
    return { republish: () => Promise.resolve(true) } as unknown as FrontierPublisher
}

describe('FetchRunner', () => {
    it('sheds every remaining URL of a domain that answered 429, and leaves the other domain alone', async () => {
        const fetcher = new FakeFetcher((url) =>
            url.includes('busy.com') ? { outcome: 'rate_limited', status: 429 } : { outcome: 'ok' }
        )
        const candidates = [
            ...[0, 1, 2].map((index) => candidate('busy.com', index)),
            ...[0, 1].map((index) => candidate('calm.com', index)),
        ]

        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1 }).run(candidates)

        expect(fetcher.calls.filter((url) => url.includes('busy.com'))).toHaveLength(1)
        expect(attempts.filter((a) => a.outcome === 'rate_limited')).toHaveLength(3)
        expect(attempts.filter((a) => a.candidate.domain === 'calm.com' && a.outcome === 'ok')).toHaveLength(2)
    })

    it('stops sending to a domain once its breaker opens', async () => {
        const fetcher = new FakeFetcher(() => ({ outcome: 'timeout' }))
        const candidates = [0, 1, 2, 3, 4, 5].map((index) => candidate('broken.com', index))

        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1 }).run(candidates)

        expect(fetcher.calls).toHaveLength(3)
        expect(attempts.filter((a) => a.outcome === 'breaker_open')).toHaveLength(3)
    })

    it('holds one domain to the configured number of connections', async () => {
        const fetcher = new FakeFetcher(() => ({ outcome: 'ok' }))

        await runner(fetcher, { maxConcurrentPerDomain: 2 }).run(
            [0, 1, 2, 3, 4, 5].map((index) => candidate('example.com', index))
        )

        expect(fetcher.peakConcurrent).toBe(2)
    })

    it('sheds what the rate would not carry before the batch budget runs out', async () => {
        const budget = new HostBudget({
            requestsPerSecond: 1,
            burst: 1,
            maxConcurrent: 4,
            breakerFailures: 100,
            breakerCooldownMs: 60_000,
            breakerMaxCooldownMs: 600_000,
            maxTrackedDomains: 100,
        })
        const fetcher = new FakeFetcher(() => ({ outcome: 'ok' }))

        // Long enough to grant the first URL whatever the machine is doing, and far shorter than
        // the wait of the second. A budget of zero makes the first grant depend on less than a
        // millisecond passing between two clock reads, which is a race a loaded runner loses.
        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1, batchBudgetMs: 50 }, budget).run(
            [0, 1, 2].map((index) => candidate('slow.com', index))
        )

        // The burst token carries the first URL. Each of the rest needs a second of waiting, which
        // the batch does not have.
        expect(fetcher.calls).toHaveLength(1)
        expect(attempts.filter((a) => a.outcome === 'deadline')).toHaveLength(2)
    })

    it('does not write off a URL whose redirect target had no budget left', async () => {
        const fetcher = new FakeFetcher(() => ({ outcome: 'redirect_deferred', status: 302 }))

        const attempts = await runner(fetcher).run([candidate('example.com', 0)])

        expect(isTerminal(attempts[0].outcome)).toBe(false)
    })

    it('handles a domain with more queued URLs than a spread can carry', async () => {
        // One batch offers up to BATCH_SIZE x MAX_URLS_PER_RECORD URLs, and the topic keys by
        // domain, so a popular CDN can fill one queue past the argument limit of Function.apply. A
        // RangeError escapes the pass, and the consumer then records nothing for the batch.
        const budget = new HostBudget({
            requestsPerSecond: 1,
            burst: 1,
            maxConcurrent: 4,
            breakerFailures: 100,
            breakerCooldownMs: 60_000,
            breakerMaxCooldownMs: 600_000,
            maxTrackedDomains: 100,
        })
        const fetcher = new FakeFetcher(() => ({ outcome: 'ok' }))
        const many = Array.from({ length: 130_000 }, (_value, index) => candidate('big.com', index))

        // A zero budget is safe here because the count below is the same whether or not the first
        // URL wins its grant. Do not copy it into a test that asserts how many requests went out,
        // because that turns on less than a millisecond passing between two clock reads.
        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1, batchBudgetMs: 0 }, budget).run(many)

        expect(attempts).toHaveLength(many.length)
    })

    it('hands a redirect off rather than following it to another domain (requirement 7)', async () => {
        const published: { domain: string; url: string; reason: string }[] = []
        const publisher = {
            republish: (candidate: FetchCandidate, target: { url: string; domain: string }, reason: string) => {
                published.push({ domain: target.domain, url: target.url, reason })
                return Promise.resolve(true)
            },
        } as unknown as FrontierPublisher
        let offsite: boolean | undefined
        const fetcher: ImageFetcher = {
            fetch: (_url, options) => {
                offsite = options.isOffsite(new URL('https://img.other-site.net/a.png'))
                return Promise.resolve({
                    outcome: 'redirect_offsite',
                    redirects: 1,
                    redirectTarget: { url: 'https://img.other-site.net/a.png', host: 'img.other-site.net' },
                })
            },
        }

        const attempts = await runner(fetcher, {}, defaultBudget(), publisher).run([candidate('example.com', 0)])

        expect(offsite).toBe(true)
        expect(published).toEqual([
            { domain: 'other-site.net', url: 'https://img.other-site.net/a.png', reason: 'redirect' },
        ])
        // The URL comes back on another partition, so a crawl history entry would stop that.
        expect(attempts[0].finished).toBe(false)
    })

    it('stops a redirect whose domain was blocked while it waited (requirement 5)', async () => {
        const budget = new HostBudget({
            requestsPerSecond: 1,
            burst: 1,
            maxConcurrent: 6,
            breakerFailures: 100,
            breakerCooldownMs: 60_000,
            breakerMaxCooldownMs: 600_000,
            maxTrackedDomains: 100,
        })
        // Spend the burst token, so the redirect below has to wait a second for the next one.
        budget.take('example.com', Date.now(), Date.now() + 60_000)
        let decision: RedirectDecision | undefined
        const fetcher: ImageFetcher = {
            fetch: async (_url, options) => {
                setTimeout(() => budget.recordRetryAfter('example.com', Date.now(), 60_000), 5)
                decision = await options.authorizeRedirect(new URL('https://img2.example.com/a.png'), 30_000)
                return { outcome: 'ok', redirects: 1 }
            },
        }

        await runner(fetcher, {}, budget).run([candidate('example.com', 0)])

        expect(decision).toBe('defer')
    })

    it('follows a redirect that stays on the same domain (requirement 6)', async () => {
        let decision: RedirectDecision | undefined
        const fetcher: ImageFetcher = {
            fetch: async (_url, options) => {
                decision = await options.authorizeRedirect(new URL('https://img2.example.com/a.png'), 5000)
                return { outcome: 'ok', redirects: 1 }
            },
        }

        await runner(fetcher).run([candidate('example.com', 0)])

        expect(decision).toBe('allow')
    })

    it('publishes a transient failure to a delay topic rather than dropping it (requirement 14)', async () => {
        const published: { reason: string; waitMs: number }[] = []
        const publisher = {
            republish: (_c: FetchCandidate, _t: unknown, reason: string, waitMs: number) => {
                published.push({ reason, waitMs })
                return Promise.resolve(true)
            },
        } as unknown as FrontierPublisher
        const fetcher = new FakeFetcher(() => ({ outcome: 'rate_limited', status: 429, retryAfterMs: 30_000 }))

        const attempts = await runner(fetcher, {}, defaultBudget(), publisher).run([candidate('busy.com', 0)])

        expect(published).toEqual([{ reason: 'retry', waitMs: 30_000 }])
        expect(attempts[0].finished).toBe(false)
    })

    it.each([
        ['a retry', { outcome: 'timeout' as const }],
        [
            'a redirect',
            {
                outcome: 'redirect_offsite' as const,
                redirectTarget: { url: 'https://cdn.other.com/i.png', host: 'cdn.other.com' },
            },
        ],
    ])(
        'reports %s the publisher could not send, so the batch does not commit past it (requirement 21)',
        async (_name, result) => {
            const publisher = { republish: () => Promise.resolve(false) } as unknown as FrontierPublisher
            const fetcher = new FakeFetcher(() => result)

            const attempts = await runner(fetcher, {}, defaultBudget(), publisher).run([candidate('example.com', 0)])

            expect(attempts[0]).toMatchObject({ finished: false, lost: true })
        }
    )

    it('reports nothing lost when the publisher sent the URL', async () => {
        const publisher = { republish: () => Promise.resolve(true) } as unknown as FrontierPublisher
        const fetcher = new FakeFetcher(() => ({ outcome: 'timeout' as const }))

        const attempts = await runner(fetcher, {}, defaultBudget(), publisher).run([candidate('example.com', 0)])

        expect(attempts[0]).toMatchObject({ finished: false, lost: false })
    })

    it('checks again when a request reaches the front of the pod queue (requirement 5)', async () => {
        // A sibling request can meet a `Retry-After` while this one waits for a pod slot, and a
        // request sent after that reaches a site which just asked to be left alone.
        const budget = defaultBudget()
        const published: string[] = []
        const publisher = {
            republish: (_c: FetchCandidate, _t: unknown, reason: string) => {
                published.push(reason)
                return Promise.resolve(true)
            },
        } as unknown as FrontierPublisher
        const fetcher: ImageFetcher = {
            fetch: async (url: string) => {
                if (url.endsWith('/0.png')) {
                    // This yields first, so the second request passes the token bucket and reaches
                    // the pod queue before the hold exists. Without the yield the token bucket
                    // refuses it, and this test passes whatever the queue does.
                    await delay(1)
                    budget.recordRetryAfter('example.com', Date.now(), 60_000)
                }
                return { outcome: 'ok' as const, redirects: 0 }
            },
        }

        const attempts = await runner(fetcher, { maxInFlightRequests: 1 }, budget, publisher).run([
            candidate('example.com', 0),
            candidate('example.com', 1),
        ])

        expect(attempts.map((attempt) => attempt.outcome).sort()).toEqual(['ok', 'rate_limited'])
        expect(published).toEqual(['retry'])
    })

    it('puts back a bounded number of shed URLs, and does it in one go', async () => {
        // A shed runs after the pass deadline has passed. One awaited produce for each URL of a
        // large back queue would run past max.poll.interval.ms and lose the partition mid-batch,
        // and putting every one of them back answers overload with more Kafka traffic.
        let open = 0
        let peak = 0
        let published = 0
        const publisher = {
            republish: async () => {
                open++
                peak = Math.max(peak, open)
                await Promise.resolve()
                published++
                open--
                return true
            },
        } as unknown as FrontierPublisher
        const fetcher = new FakeFetcher(() => ({ outcome: 'rate_limited', status: 429, retryAfterMs: 30_000 }))
        const queue = Array.from({ length: 2500 }, () => candidate('busy.com', 0))

        const attempts = await runner(fetcher, {}, defaultBudget(), publisher).run(queue)

        expect(attempts).toHaveLength(2500)
        // The cap, plus the few that held a burst token and were fetched before the 429 blocked the
        // domain. Well under 2500, which is what one awaited produce for each would have cost.
        expect(published).toBeGreaterThanOrEqual(1000)
        expect(published).toBeLessThanOrEqual(1000 + OPTIONS.maxConcurrentPerDomain)
        // More than one produce was open at a time, so the shed did not await them one by one.
        expect(peak).toBeGreaterThan(1)
    })

    it('bounds the shed republish across the whole pass, not once for each domain', async () => {
        // Domains run at the same time, so an allowance for each of them multiplies by however many
        // a batch touches. One busy domain per record of a full batch would open that many times
        // the cap as Kafka produces at once, past what the producer queue holds.
        let open = 0
        let peak = 0
        let published = 0
        const publisher = {
            republish: async () => {
                open++
                peak = Math.max(peak, open)
                await Promise.resolve()
                published++
                open--
                return true
            },
        } as unknown as FrontierPublisher
        const fetcher = new FakeFetcher(() => ({ outcome: 'rate_limited', status: 429, retryAfterMs: 30_000 }))
        // 40 domains, 100 URLs each. A per-domain cap of 1000 would put back all 4000.
        const queue = Array.from({ length: 40 }).flatMap((_unused, domain) =>
            Array.from({ length: 100 }, () => candidate(`site${domain}.com`, 0))
        )

        const attempts = await runner(fetcher, {}, defaultBudget(), publisher).run(queue)

        expect(attempts).toHaveLength(4000)
        // The pass allowance, plus the few per domain that held a burst token and were fetched.
        expect(published).toBeLessThanOrEqual(1000 + 40 * OPTIONS.maxConcurrentPerDomain)
        expect(peak).toBeLessThanOrEqual(1000 + 40 * OPTIONS.maxConcurrentPerDomain)
    })

    it('gives up and records a URL with no hops left (requirement 12)', async () => {
        const publisher = { republish: () => Promise.resolve(true) } as unknown as FrontierPublisher
        const fetcher = new FakeFetcher(() => ({ outcome: 'timeout' }))
        const spent = { ...candidate('example.com', 0), hopsRemaining: 1 }

        const attempts = await runner(fetcher, {}, defaultBudget(), publisher).run([spent])

        expect(attempts[0]).toMatchObject({ outcome: 'hops_exhausted', finished: true })
    })

    it('runs every domain at once but holds the requests under them to the in-flight limit', async () => {
        let inFlight = 0
        let peak = 0
        const fetcher: ImageFetcher = {
            fetch: async () => {
                peak = Math.max(peak, ++inFlight)
                await new Promise((resolve) => setTimeout(resolve, 5))
                inFlight--
                return { outcome: 'ok', redirects: 0 }
            },
        }
        const domains = Array.from({ length: 60 }, (_value, index) => candidate(`site${index}.com`, 0))

        const attempts = await runner(fetcher, { maxInFlightRequests: 5 }).run(domains)

        expect(peak).toBe(5)
        expect(attempts.filter((a) => a.outcome === 'ok')).toHaveLength(60)
    })

    it.each([
        ['a 429', 'rate_limited' as const, undefined, true],
        ['a 503 that named a period', 'server_error' as const, 30_000, true],
        ['a one-off 500', 'server_error' as const, undefined, false],
    ])('holds the whole domain after %s: %s', async (_name, outcome, retryAfterMs, expectHeld) => {
        // A hold silences every URL of the domain. A site that failed one request did not ask for
        // that, so it gets the rate cut and the breaker count instead.
        const fetcher = new FakeFetcher(() => ({ outcome, status: 500, retryAfterMs }))

        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1 }).run(
            [0, 1].map((index) => candidate('site.com', index))
        )

        expect(attempts.some((a) => a.outcome === 'rate_limited')).toBe(expectHeld)
    })

    it('does not send a request whose domain was blocked while it waited (requirement 5)', async () => {
        const budget = new HostBudget({
            requestsPerSecond: 1,
            burst: 1,
            maxConcurrent: 6,
            breakerFailures: 100,
            breakerCooldownMs: 60_000,
            breakerMaxCooldownMs: 600_000,
            maxTrackedDomains: 100,
        })
        const fetcher = new FakeFetcher(() => ({ outcome: 'ok' }))
        // The burst token carries the first URL. The second waits a second for its token, and the
        // site says stop during that wait.
        setTimeout(() => budget.recordRetryAfter('slow.com', Date.now(), 60_000), 5)

        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1 }, budget).run(
            [0, 1].map((index) => candidate('slow.com', index))
        )

        expect(fetcher.calls).toHaveLength(1)
        expect(attempts.filter((a) => a.outcome === 'rate_limited')).toHaveLength(1)
    })

    it('returns the token of a request it did not send (requirement 5)', () => {
        const budget = new HostBudget({
            requestsPerSecond: 1,
            burst: 2,
            maxConcurrent: 6,
            breakerFailures: 100,
            breakerCooldownMs: 60_000,
            breakerMaxCooldownMs: 600_000,
            maxTrackedDomains: 100,
        })
        budget.take('example.com', 1000, FAR_FUTURE)
        budget.take('example.com', 1000, FAR_FUTURE)

        budget.returnGrant('example.com', 1000)

        expect(budget.take('example.com', 1000, FAR_FUTURE)).toEqual({ granted: true, waitMs: 0 })
    })

    it.each([
        ['ok', true],
        ['not_found', true],
        ['too_large', true],
        ['blocked', true],
        ['timeout', false],
        ['rate_limited', false],
        ['server_error', false],
        ['breaker_open', false],
        ['deadline', false],
    ])('treats %s as terminal: %s', (outcome, terminal) => {
        // A terminal outcome writes a crawl history entry, which is the one thing that stops this
        // lane from looking at the URL again. A transient outcome must not write one.
        expect(isTerminal(outcome as FetchOutcome)).toBe(terminal)
    })
})
