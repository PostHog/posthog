import { flushOnAgePredicate } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-blob-consumer'

describe('flush on age predicate', () => {
    it.each([
        ['copes when times are back to front', 100, 100, 0, 201, false, -101],
        ['does not flush exactly on threshold', 200, 100, 0, 100, false, 100],
        ['flushes when past threshold', 200, 100, 0, 99, true, 101],
        ['flushes when not past threshold and attempt count is not yet too high', 200, 100, 30, 199, false, 1],
        ['flushes when not past threshold but attempt count is too high', 200, 100, 31, 199, true, 1],
    ])(
        'flush predicate behaves as expected: %s',
        (
            _description,
            referenceNow,
            flushThreshold,
            referenceNowFlushAttemptCount,
            sessionStartTimestamp,
            expectedFlush,
            expectedBufferAge
        ) => {
            const predicate = flushOnAgePredicate(referenceNow, flushThreshold, referenceNowFlushAttemptCount)
            const result = predicate(sessionStartTimestamp)
            expect(result.shouldFlush).toEqual(expectedFlush)
            expect(result.extraLogContext.bufferAge).toEqual(expectedBufferAge)
        }
    )
})
