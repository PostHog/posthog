import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { FetchCandidateQueue } from './fetch-candidate-queue'

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

describe('FetchCandidateQueue', () => {
    it('drains a maximum-sized diverse poll batch without scanning every remaining origin', () => {
        const candidateCount = 50_000
        const queue = new FetchCandidateQueue(
            Array.from({ length: candidateCount }, (_, index) => candidate(index)),
            {
                maxConcurrentPerRegistrableDomain: 6,
                minimumActiveOrigins: 8,
                lowOriginDiversityRepublishThreshold: 50,
                lowOriginDiversityProgress: 8,
            }
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
                maxConcurrentPerRegistrableDomain: 1,
                minimumActiveOrigins: 1,
                lowOriginDiversityRepublishThreshold: 100_000,
                lowOriginDiversityProgress: 8,
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
})
