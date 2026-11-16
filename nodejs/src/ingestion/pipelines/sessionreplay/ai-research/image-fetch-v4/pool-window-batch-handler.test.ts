import { Message } from 'node-rdkafka'

import { MAX_HOPS } from './collected-urls-record'
import { FetchCandidatePool, FetchCandidatePoolAdmission } from './fetch-candidate-pool'
import { createPoolWindowBatchHandler } from './pool-window-batch-handler'

const NOW_MS = 1_700_000_000_000
const MESSAGE: Message = {
    topic: 'session_replay_image_fetch',
    partition: 3,
    offset: 1,
    value: Buffer.from('x'),
    size: 1,
}

function distinctDomainCandidates(count: number): Parameters<FetchCandidatePool<string>['add']>[0] {
    return Array.from({ length: count }, (_unused, index) => ({
        originalRef: `imageurl:${index}`,
        currentUrl: `https://cdn${index}.example${index}.com/a.png`,
        host: `cdn${index}.example${index}.com`,
        origin: `https://cdn${index}.example${index}.com`,
        registrableDomain: `example${index}.com`,
        remainingHops: MAX_HOPS,
        notBeforeMs: 0,
        firstSeenAtMs: NOW_MS,
        fetchCount: 0,
        republishCount: 0,
        lastRepublishReason: null,
    }))
}

describe('createPoolWindowBatchHandler', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(NOW_MS))
    afterEach(() => jest.useRealTimers())

    it.each([
        ['returns once the batch enters the pool and the window has room', 0, 500],
        ['returns at the wait cap while the window stays full', 20, 30_000],
    ])('%s', async (_name, queuedAfterAdmission, expectedReturnMs) => {
        const pool = new FetchCandidatePool<string>(
            { maxConcurrentPerRegistrableDomain: 6, refillRunnableUrls: 10, maxQueuedUrlsPerOwner: 1_000 },
            { originCrawlDelayMs: () => 0, originNextImageStartAtMs: () => 0 }
        )
        const owner = pool.createOwner()
        let finishBatch: () => void = () => undefined
        const processBatch = jest.fn(
            (_messages: Message[], admission: FetchCandidatePoolAdmission) =>
                new Promise<void>((resolve) => {
                    setTimeout(() => {
                        pool.add(
                            distinctDomainCandidates(queuedAfterAdmission),
                            'batch',
                            NOW_MS + 40_000,
                            admission.owner
                        )
                        admission.admitted()
                    }, 500)
                    finishBatch = resolve
                })
        )
        const handler = createPoolWindowBatchHandler(owner, processBatch)

        let returnedAtMs: number | undefined
        const returned = handler([MESSAGE]).then((result) => {
            returnedAtMs = Date.now()
            return result
        })
        await jest.advanceTimersByTimeAsync(30_000)
        const result = await returned
        finishBatch()

        expect(processBatch).toHaveBeenCalledTimes(1)
        expect(returnedAtMs! - NOW_MS).toBe(expectedReturnMs)
        await expect(result?.backgroundTask).resolves.toBeUndefined()
        pool.close()
    })
})
