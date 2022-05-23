import { PreIngestionEvent } from '../../../../src/types'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/createEventStep'

jest.mock('../../../../src/worker/plugins/run')

const preIngestionEvent: PreIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00Z',
    event: '$pageview',
    properties: {},
    elementsList: [],
}

const testPerson: any = { id: 'testid' }
const testElements: any = ['element1', 'element2']

describe('createEventStep()', () => {
    let runner: any

    beforeEach(() => {
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
                eventsProcessor: {
                    createEvent: () => [null, null, testElements],
                },
            },
        }
    })

    it('calls `createEvent` and forwards to `runAsyncHandlersStep`', async () => {
        const response = await createEventStep(runner, preIngestionEvent, testPerson)

        expect(response).toEqual(['runAsyncHandlersStep', preIngestionEvent, testPerson, testElements])
    })
})
