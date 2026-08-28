import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { FetchCandidateQueue } from './fetch-candidate-queue'

const OPTIONS = {
    maxConcurrentPerRegistrableDomain: 6,
    maxInFlightRequests: 300,
}

function candidate(index: number): FetchCandidate {
    return {
        originalRef: `ref-${index}`,
        currentUrl: `https://origin-${index}.example.com/image.png`,
        host: `origin-${index}.example.com`,
        origin: `https://origin-${index}.example.com`,
        registrableDomain: 'example.com',
        remainingHops: MAX_HOPS,
        notBeforeMs: 0,
        firstSeenAtMs: 1_700_000_000_000,
        fetchCount: 0,
        republishCount: 0,
        lastRepublishReason: null,
    }
}

function dominantOriginCandidate(index: number): FetchCandidate {
    return {
        ...candidate(index),
        currentUrl: `https://dominant.example.com/${index}.png`,
        host: 'dominant.example.com',
        origin: 'https://dominant.example.com',
    }
}

function domainCandidate(domainIndex: number, candidateIndex: number): FetchCandidate {
    const index = domainIndex * 1_000 + candidateIndex
    const registrableDomain = `domain-${domainIndex}.example`
    return {
        ...candidate(index),
        currentUrl: `https://cdn.${registrableDomain}/${candidateIndex}.png`,
        host: `cdn.${registrableDomain}`,
        origin: `https://cdn.${registrableDomain}`,
        registrableDomain,
    }
}

function concurrentDomainCounts(queue: FetchCandidateQueue, count: number): Map<string, number> {
    const counts = new Map<string, number>()
    for (let index = 0; index < count; index++) {
        const lease = queue.take()
        expect(lease).toBeDefined()
        if (lease) {
            counts.set(lease.candidate.registrableDomain, (counts.get(lease.candidate.registrableDomain) ?? 0) + 1)
        }
    }
    return counts
}

describe('FetchCandidateQueue', () => {
    it('drains a maximum-sized diverse poll batch without scanning every remaining origin', () => {
        const candidateCount = 50_000
        const queue = new FetchCandidateQueue(
            Array.from({ length: candidateCount }, (_, index) => candidate(index)),
            OPTIONS
        )
        let drained = 0

        for (;;) {
            const lease = queue.take()
            if (!lease) {
                break
            }
            drained += 1
            lease.release()
        }

        expect(drained).toBe(candidateCount)
    })

    it('keeps one selectable domain entry during a long dominant-origin run', () => {
        const dominantCandidateCount = 50_000
        const queue = new FetchCandidateQueue(
            [
                ...Array.from({ length: dominantCandidateCount }, (_, index) => dominantOriginCandidate(index)),
                candidate(dominantCandidateCount),
            ],
            {
                ...OPTIONS,
                maxConcurrentPerRegistrableDomain: 1,
            }
        )
        let drained = 0
        let maximumSelectableDomains = 0

        for (;;) {
            const lease = queue.take()
            if (!lease) {
                break
            }
            drained += 1
            lease.release()
            maximumSelectableDomains = Math.max(maximumSelectableDomains, queue.selectableRegistrableDomainCount)
        }

        expect(drained).toBe(dominantCandidateCount + 1)
        expect(maximumSelectableDomains).toBe(1)
    })

    it.each([
        {
            name: 'gives 150 equal domains two requests each',
            domainSizes: Array.from({ length: 150 }, () => 6),
            expectedCounts: Array.from({ length: 150 }, () => 2),
        },
        {
            name: 'gives smaller domains their proportional request share',
            domainSizes: [...Array.from({ length: 50 }, () => 100), ...Array.from({ length: 50 }, () => 10)],
            expectedCounts: [...Array.from({ length: 50 }, () => 5), ...Array.from({ length: 50 }, () => 1)],
        },
    ])('$name', ({ domainSizes, expectedCounts }) => {
        const queue = new FetchCandidateQueue(
            domainSizes.flatMap((size, domainIndex) =>
                Array.from({ length: size }, (_, candidateIndex) => domainCandidate(domainIndex, candidateIndex))
            ),
            OPTIONS
        )

        const counts = concurrentDomainCounts(queue, OPTIONS.maxInFlightRequests)

        expect(
            Array.from({ length: domainSizes.length }, (_, index) => counts.get(`domain-${index}.example`) ?? 0)
        ).toEqual(expectedCounts)
    })
})
