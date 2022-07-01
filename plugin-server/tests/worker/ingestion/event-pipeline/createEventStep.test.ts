import { IngestionEvent } from '../../../../src/types'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/5-createEventStep'

jest.mock('../../../../src/worker/plugins/run')

const preIngestionEvent: IngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00Z',
    event: '$pageview',
    properties: {},
    elementsList: [],
    person: { id: 'testid' } as any,
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

    it('calls `createEvent` and forwards to `runAsyncHandlersStep`', async () => {
        const response = await createEventStep(runner, preIngestionEvent)

        expect(response).toEqual(['runAsyncHandlersStep', preIngestionEvent])
    })
})
