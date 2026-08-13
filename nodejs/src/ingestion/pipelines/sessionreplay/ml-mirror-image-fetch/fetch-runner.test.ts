import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { FetchRunner, FetchRunnerOptions, isTerminal } from './fetch-runner'
import { HostBudget } from './host-budget'
import { FetchOutcome, ImageFetchResult, ImageFetcher } from './image-fetcher'

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
    })
): FetchRunner {
    return new FetchRunner(fetcher, budget, { ...OPTIONS, ...options })
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

        // One request tells us the whole domain is rate limited, so the rest never go out.
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

        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1, batchBudgetMs: 0 }, budget).run(
            [0, 1, 2].map((index) => candidate('slow.com', index))
        )

        // The burst token carries the first. The rest would each need a second of waiting, which the
        // batch does not have, so they are left for the next session that refers to them.
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
        // domain, so a popular CDN can fill a single queue past the argument limit of Function.apply.
        // A RangeError here escapes the pass, and the consumer then records nothing for the batch.
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

        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1, batchBudgetMs: 0 }, budget).run(many)

        expect(attempts).toHaveLength(many.length)
    })

    it('holds a redirect target to its own connection limit', async () => {
        // Two source domains redirect to one CDN. Without a slot taken for the target, each source
        // worker opens its own connection and the CDN sees more than its configured maximum.
        const budget = new HostBudget({
            requestsPerSecond: 1000,
            burst: 1000,
            maxConcurrent: 1,
            breakerFailures: 100,
            breakerCooldownMs: 60_000,
            breakerMaxCooldownMs: 600_000,
            maxTrackedDomains: 100,
        })
        const targets: string[] = []
        const fetcher: ImageFetcher = {
            fetch: async (url, options) => {
                const decision = await options.authorizeRedirect(new URL('https://img.shared-cdn.net/a.png'), 5000)
                targets.push(`${url}:${decision}`)
                // Held open until both source domains have asked, so the two overlap.
                await new Promise((resolve) => setTimeout(resolve, 20))
                return { outcome: 'ok', redirects: 1 }
            },
        }

        await runner(fetcher, { maxConcurrentPerDomain: 1 }, budget).run([
            candidate('one.com', 0),
            candidate('two.com', 0),
        ])

        expect(targets.filter((t) => t.endsWith(':allow'))).toHaveLength(1)
        expect(targets.filter((t) => t.endsWith(':defer'))).toHaveLength(1)
    })

    it('runs every domain at once but holds the requests under them to the in-flight limit', async () => {
        // The politeness limit is per domain, and one domain lands on one partition and one pod, so
        // a pod owning many domains has to serve them all. What bounds the pod is the requests.
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
        // A hold silences every URL of the domain. A site that only failed one request has not
        // asked for that, so it gets the rate cut and the breaker count instead.
        const fetcher = new FakeFetcher(() => ({ outcome, status: 500, retryAfterMs }))

        const attempts = await runner(fetcher, { maxConcurrentPerDomain: 1 }).run(
            [0, 1].map((index) => candidate('site.com', index))
        )

        expect(attempts.some((a) => a.outcome === 'rate_limited')).toBe(expectHeld)
    })

    it('does not send a request whose domain was blocked while it waited (requirement 5)', async () => {
        // The grant is made before the wait. A Retry-After arriving during the wait must stop the
        // request, because the site asked to be left alone after we decided to send.
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
        // site says stop while it is waiting.
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

        // A request that never went out did not use the rate, so the token comes back.
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
        // A terminal outcome writes a crawl history entry, which is the one thing that stops this lane from
        // ever looking at the URL again. A transient one must not.
        expect(isTerminal(outcome as FetchOutcome)).toBe(terminal)
    })
})
