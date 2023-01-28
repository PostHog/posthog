import { ISOTimestamp, PreIngestionEvent } from '../../../../src/types'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/createEventStep'
import { LazyPersonContainer } from '../../../../src/worker/ingestion/lazy-person-container'

jest.mock('../../../../src/worker/plugins/run')

const preIngestionEvent: PreIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: [],
}

describe('createEventStep()', () => {
    let runner: any

    beforeEach(() => {
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
                eventsProcessor: {
                    createEvent: jest.fn().mockReturnValue(preIngestionEvent),
                },
            },
        }
    })

    it("calls `createEvent` and doesn't advance to the async handlers step", async () => {
        const personContainer = new LazyPersonContainer(2, 'my_id', runner.hub)
        const response = await createEventStep(runner, preIngestionEvent, personContainer)

        expect(response).toEqual(null) // async handlers are handled separately by reading from the clickhouse events topic
    })
})
