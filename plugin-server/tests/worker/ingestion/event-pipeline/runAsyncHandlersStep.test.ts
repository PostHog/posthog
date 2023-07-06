import { ISOTimestamp, PostIngestionEvent } from '../../../../src/types'
import { convertToProcessedPluginEvent } from '../../../../src/utils/event'
import {
    processOnEventStep,
    processWebhooksStep,
} from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { runOnEvent, runOnSnapshot } from '../../../../src/worker/plugins/run'

jest.mock('../../../../src/worker/plugins/run')

const testElements: any = ['element1', 'element2']
const ingestionEvent: PostIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
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
            nextStep: (...args: any[]) => args,
            hub: {
                capabilities: {
                    processAsyncOnEventHandlers: true,
                },
                actionMatcher: {
                    match: jest.fn().mockResolvedValue(['action1', 'action2']),
                },
                hookCannon: {
                    findAndFireHooks: jest.fn().mockResolvedValue(true),
                },
            },
        }
    })

    it('stops processing', async () => {
        const response = await processOnEventStep(runner, ingestionEvent)

        expect(response).toEqual(null)
    })

    it('does action matching and fires webhooks', async () => {
        await processWebhooksStep(runner, ingestionEvent)

        expect(runner.hub.actionMatcher.match).toHaveBeenCalled()
        expect(runner.hub.hookCannon.findAndFireHooks).toHaveBeenCalledWith(ingestionEvent, ['action1', 'action2'])
    })

    it('calls onEvent plugin methods', async () => {
        await processOnEventStep(runner, ingestionEvent)

        expect(runOnEvent).toHaveBeenCalledWith(runner.hub, convertToProcessedPluginEvent(ingestionEvent))
        expect(runOnSnapshot).not.toHaveBeenCalled()
    })
})
