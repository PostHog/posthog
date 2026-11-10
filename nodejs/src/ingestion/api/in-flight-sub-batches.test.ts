import { logger } from '~/common/utils/logger'

import { FedSubBatch, InFlightSubBatches } from './in-flight-sub-batches'

function subBatch(streamId: number, seq: number): FedSubBatch {
    return {
        streamId,
        seq,
        consumerId: `consumer-${streamId}`,
        streamEpoch: '1',
        assignmentEpoch: '1',
        messages: [{ topic: 'events', partition: 0, offset: seq, timestamp: 0, key: 'k', value: '{}', headers: {} }],
    }
}

describe('InFlightSubBatches', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: 0 })
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('finds unsettled sub-batches past the deadline and reports whether their stream ended', () => {
        const errorLog = jest.spyOn(logger, 'error')
        const inFlight = new InFlightSubBatches(100)
        inFlight.onFed(subBatch(1, 1))
        inFlight.onFed(subBatch(2, 1))
        inFlight.onFed(subBatch(3, 1))
        jest.setSystemTime(50)
        inFlight.onFed(subBatch(4, 1))
        inFlight.onSettled(1, 1, 'ok', 1)
        inFlight.onStreamEnded(2)

        const stuck = inFlight.findStuck(101)
        inFlight.reportStuck(stuck)

        expect(stuck).toEqual([
            { key: '2:1', streamId: 2, inFlightMs: 101 },
            { key: '3:1', streamId: 3, inFlightMs: 101 },
        ])
        expect(errorLog.mock.calls.map(([, , fields]) => fields)).toEqual([
            expect.objectContaining({ key: '2:1', streamOpen: false }),
            expect.objectContaining({ key: '3:1', streamOpen: true }),
        ])
    })
})
