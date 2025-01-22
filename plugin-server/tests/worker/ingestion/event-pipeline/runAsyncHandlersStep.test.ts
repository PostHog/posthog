import { ISOTimestamp, PostIngestionEvent } from '../../../../src/types'
import { processOnEventStep } from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { runOnEvent } from '../../../../src/worker/plugins/run'

jest.mock('../../../../src/worker/plugins/run')

const testElements: any = ['element1', 'element2']
const ingestionEvent: PostIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: testElements,
    person_id: 'testid',
    person_created_at: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    person_properties: {},
}

describe('runAsyncHandlersStep()', () => {
    let runner: any

    beforeEach(() => {
        runner = {
            hub: {
                capabilities: {
                    processAsyncOnEventHandlers: true,
                },
                hookCannon: {
                    findAndFireHooks: jest.fn().mockResolvedValue(true),
                },
            },
        }
    })

    it('stops processing', async () => {
        const response = await processOnEventStep(runner.hub, ingestionEvent)

        expect(response).toEqual(null)
    })

    it('calls onEvent plugin methods', async () => {
        await processOnEventStep(runner.hub, ingestionEvent)

        expect(runOnEvent).toHaveBeenCalledWith(runner.hub, ingestionEvent)
    })
})
