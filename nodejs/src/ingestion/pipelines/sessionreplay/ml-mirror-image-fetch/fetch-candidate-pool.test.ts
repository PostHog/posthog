import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { FetchCandidatePool, FetchCandidatePoolLease, OriginPacing } from './fetch-candidate-pool'

const NOW_MS = 1_700_000_000_000

function candidate(url: string, registrableDomain: string): FetchCandidate {
    const parsed = new URL(url)
    return {
        originalRef: `imageurl:${url}`,
        currentUrl: url,
        host: parsed.host,
        origin: parsed.origin,
        registrableDomain,
        remainingHops: MAX_HOPS,
        notBeforeMs: 0,
        firstSeenAtMs: NOW_MS,
        fetchCount: 0,
        republishCount: 0,
        lastRepublishReason: null,
    }
}

function buildPool(
    crawlDelayMsByOrigin: Record<string, number> = {},
    limits: { maxConcurrentPerRegistrableDomain?: number; refillRunnableUrls?: number } = {}
): FetchCandidatePool<string> {
    const pacing: OriginPacing = {
        originCrawlDelayMs: (origin) => crawlDelayMsByOrigin[origin] ?? 0,
        originNextImageStartAtMs: () => 0,
    }
    return new FetchCandidatePool<string>(
        {
            maxConcurrentPerRegistrableDomain: limits.maxConcurrentPerRegistrableDomain ?? 2,
            refillRunnableUrls: limits.refillRunnableUrls ?? 3,
            maxQueuedUrlsPerOwner: 100,
        },
        pacing
    )
}

async function takeReady(pool: FetchCandidatePool<string>): Promise<FetchCandidatePoolLease<string> | undefined> {
    let lease: FetchCandidatePoolLease<string> | undefined
    let settled = false
    void pool.take().then((taken) => {
        lease = taken
        settled = true
    })
    await jest.advanceTimersByTimeAsync(0)
    if (!settled) {
        pool.close()
        await jest.advanceTimersByTimeAsync(0)
    }
    return lease
}

describe('FetchCandidatePool', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(NOW_MS))
    afterEach(() => jest.useRealTimers())

    it('takes the oldest candidate of a domain under its limit, across batches from different partitions', async () => {
        const pool = buildPool()
        pool.add(
            [
                candidate('https://cdn.hot.com/1.png', 'hot.com'),
                candidate('https://cdn.hot.com/2.png', 'hot.com'),
                candidate('https://cdn.hot.com/3.png', 'hot.com'),
            ],
            'partition-1',
            NOW_MS + 40_000
        )
        jest.advanceTimersByTime(10)
        pool.add([candidate('https://cdn.quiet.com/1.png', 'quiet.com')], 'partition-2', NOW_MS + 40_000)

        const leases = [await takeReady(pool), await takeReady(pool), await takeReady(pool)]

        expect(leases.map((lease) => lease?.candidate.currentUrl)).toEqual([
            'https://cdn.hot.com/1.png',
            'https://cdn.hot.com/2.png',
            'https://cdn.quiet.com/1.png',
        ])
        expect(leases[2]?.context).toBe('partition-2')
        expect(await takeReady(pool)).toBeUndefined()
    })

    it('frees the domain slot on release, not before', async () => {
        const pool = buildPool({}, { maxConcurrentPerRegistrableDomain: 1 })
        pool.add(
            [candidate('https://cdn.hot.com/1.png', 'hot.com'), candidate('https://img.hot.com/2.png', 'hot.com')],
            'partition-1',
            NOW_MS + 40_000
        )

        const first = await takeReady(pool)
        const waiting = pool.take()
        await jest.advanceTimersByTimeAsync(0)
        first?.release()

        expect((await waiting)?.candidate.currentUrl).toBe('https://img.hot.com/2.png')
    })

    it('holds an origin until its crawl delay passes while other origins keep running', async () => {
        const pool = buildPool({ 'https://slow.example.com': 5_000 })
        pool.add(
            [
                candidate('https://slow.example.com/1.png', 'example.com'),
                candidate('https://slow.example.com/2.png', 'example.com'),
                candidate('https://fast.other.net/1.png', 'other.net'),
            ],
            'partition-1',
            NOW_MS + 40_000
        )

        const first = await takeReady(pool)
        const second = await takeReady(pool)
        const delayed = pool.take()
        await jest.advanceTimersByTimeAsync(4_999)
        let delayedTaken = false
        void delayed.then(() => {
            delayedTaken = true
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(delayedTaken).toBe(false)
        await jest.advanceTimersByTimeAsync(1)

        expect([first, second, await delayed].map((lease) => lease?.candidate.currentUrl)).toEqual([
            'https://slow.example.com/1.png',
            'https://fast.other.net/1.png',
            'https://slow.example.com/2.png',
        ])
    })

    it('hands out a batch past its deadline without a domain slot', async () => {
        const pool = buildPool({}, { maxConcurrentPerRegistrableDomain: 1 })
        pool.add(
            [candidate('https://cdn.hot.com/1.png', 'hot.com'), candidate('https://cdn.hot.com/2.png', 'hot.com')],
            'partition-1',
            NOW_MS + 1_000
        )
        const held = await takeReady(pool)
        await jest.advanceTimersByTimeAsync(1_001)

        expect(held?.candidate.currentUrl).toBe('https://cdn.hot.com/1.png')
        expect((await takeReady(pool))?.candidate.currentUrl).toBe('https://cdn.hot.com/2.png')
        expect(pool.candidateCount).toBe(0)
    })

    it('withdraws the queued candidates of a failed batch only', async () => {
        const pool = buildPool()
        const failed = pool.add(
            [
                candidate('https://a.example.com/1.png', 'example.com'),
                candidate('https://b.example.com/2.png', 'example.com'),
            ],
            'failed',
            NOW_MS + 40_000
        )
        pool.add([candidate('https://c.other.net/1.png', 'other.net')], 'healthy', NOW_MS + 40_000)

        await takeReady(pool)

        expect(pool.withdraw(failed)).toBe(1)
        expect((await takeReady(pool))?.context).toBe('healthy')
        expect(await takeReady(pool)).toBeUndefined()
    })

    it.each([
        ['counts a hot domain only up to its limit, so the owner still has room', 10, 'hot.com', true],
        ['has no room once enough distinct domains can run', 1, 'domain', false],
    ])('%s', (_name, urlsPerDomain, domainPrefix, expectedRoom) => {
        const pool = buildPool({}, { maxConcurrentPerRegistrableDomain: 2, refillRunnableUrls: 3 })
        const owner = pool.createOwner()
        const candidates = Array.from({ length: 10 }, (_unused, index) => {
            const domain = urlsPerDomain === 10 ? domainPrefix : `${domainPrefix}${index}.com`
            return candidate(`https://cdn.${domain}/${index}.png`, domain)
        })

        pool.add(candidates, 'partition-1', NOW_MS + 40_000, owner)

        expect(owner.queuedUrls).toBe(10)
        expect(owner.hasRoom()).toBe(expectedRoom)
    })

    it('keeps an owner without room while a batch waits for admission', async () => {
        const pool = buildPool()
        const owner = pool.createOwner()
        const admission = owner.beginAdmission()
        let hadRoom: boolean | undefined
        void owner.waitForRoom(30_000).then((room) => {
            hadRoom = room
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(hadRoom).toBeUndefined()

        admission.admitted()
        await jest.advanceTimersByTimeAsync(0)

        expect(hadRoom).toBe(true)
    })

    it('gives an owner room when a fetch worker finds nothing eligible, even with runnable URLs queued', async () => {
        const pool = new FetchCandidatePool<string>(
            { maxConcurrentPerRegistrableDomain: 2, refillRunnableUrls: 3, maxQueuedUrlsPerOwner: 100 },
            { originCrawlDelayMs: () => 5_000, originNextImageStartAtMs: () => NOW_MS + 5_000 }
        )
        const owner = pool.createOwner()
        const delayedCandidates = Array.from({ length: 5 }, (_unused, index) =>
            candidate(`https://cdn.site${index}.com/a.png`, `site${index}.com`)
        )
        pool.add(delayedCandidates, 'partition-1', NOW_MS + 40_000, owner)
        let hadRoom: boolean | undefined
        void owner.waitForRoom(30_000).then((room) => {
            hadRoom = room
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(owner.hasRoom()).toBe(false)
        expect(hadRoom).toBeUndefined()

        void pool.take()
        await jest.advanceTimersByTimeAsync(0)

        expect(hadRoom).toBe(true)
        pool.close()
    })
})
