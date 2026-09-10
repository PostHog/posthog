import { Message } from 'node-rdkafka'

import { IMAGE_FETCH_BATCH_JOIN_TIMEOUT_MS, ImageFetchBatchJoiner } from './image-fetch-batch-joiner'

function message(partition: number): Message {
    return {
        topic: 'session_replay_image_fetch',
        partition,
        offset: 1,
        value: Buffer.from(`partition-${partition}`),
        size: 11,
    }
}

function deferred(): { promise: Promise<void>; resolve: () => void; reject: (error: unknown) => void } {
    let resolve!: () => void
    let reject!: (error: unknown) => void
    const promise = new Promise<void>((done, fail) => {
        resolve = done
        reject = fail
    })
    return { promise, resolve, reject }
}

describe('ImageFetchBatchJoiner', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it('joins batches from two consumers before processing', async () => {
        const processBatch = jest.fn(() => Promise.resolve())
        const joiner = new ImageFetchBatchJoiner(2, processBatch)

        const first = joiner.handleBatch([message(0)])
        expect(processBatch).not.toHaveBeenCalled()
        const second = joiner.handleBatch([message(1)])

        await Promise.all([first, second])
        expect(processBatch).toHaveBeenCalledWith([message(0), message(1)])
    })

    it('processes one available batch when the join window ends', async () => {
        const processBatch = jest.fn(() => Promise.resolve())
        const joiner = new ImageFetchBatchJoiner(2, processBatch)

        const pending = joiner.handleBatch([message(0)])
        await jest.advanceTimersByTimeAsync(IMAGE_FETCH_BATCH_JOIN_TIMEOUT_MS - 1)
        expect(processBatch).not.toHaveBeenCalled()
        await jest.advanceTimersByTimeAsync(1)

        await pending
        expect(processBatch).toHaveBeenCalledWith([message(0)])
    })

    it('rejects active and pending consumers when processing fails', async () => {
        const error = new Error('fetch pass failed')
        const pass = deferred()
        const joiner = new ImageFetchBatchJoiner(2, () => pass.promise)

        const first = joiner.handleBatch([message(0)])
        await jest.advanceTimersByTimeAsync(IMAGE_FETCH_BATCH_JOIN_TIMEOUT_MS)
        const second = joiner.handleBatch([message(1)])
        pass.reject(error)

        await expect(first).rejects.toBe(error)
        await expect(second).rejects.toBe(error)
    })

    it('does not hold a later partial batch behind active processing', async () => {
        const firstPass = deferred()
        const secondPass = deferred()
        const processBatch = jest
            .fn()
            .mockImplementationOnce(() => firstPass.promise)
            .mockImplementationOnce(() => secondPass.promise)
        const joiner = new ImageFetchBatchJoiner(2, processBatch)

        const first = joiner.handleBatch([message(0)])
        await jest.advanceTimersByTimeAsync(IMAGE_FETCH_BATCH_JOIN_TIMEOUT_MS)
        const second = joiner.handleBatch([message(1)])
        await jest.advanceTimersByTimeAsync(IMAGE_FETCH_BATCH_JOIN_TIMEOUT_MS)
        expect(processBatch).toHaveBeenCalledTimes(2)

        secondPass.resolve()
        await second
        firstPass.resolve()
        await first
        expect(processBatch).toHaveBeenLastCalledWith([message(1)])
    })
})
