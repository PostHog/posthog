import { FetchCandidate } from './collected-urls-record'
import { FetchRunner, FetchRunnerOptions, isTerminal } from './fetch-runner'
import { HostBudget } from './host-budget'
import { FetchOutcome, ImageFetchResult, ImageFetcher } from './image-fetcher'

const OPTIONS: FetchRunnerOptions = {
    maxConcurrentPerDomain: 2,
    maxConcurrentDomains: 8,
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

function runner(
    fetcher: ImageFetcher,
    options: Partial<FetchRunnerOptions> = {},
    budget = new HostBudget({
        requestsPerSecond: 1000,
        burst: 1000,
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
        // A terminal outcome writes a sighting, which is the one thing that stops this lane from
        // ever looking at the URL again. A transient one must not.
        expect(isTerminal(outcome as FetchOutcome)).toBe(terminal)
    })
})
