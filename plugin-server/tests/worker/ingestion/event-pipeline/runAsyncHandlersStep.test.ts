import { ISOTimestamp, PostIngestionEvent } from '../../../../src/types'
import { processWebhooksStep } from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'

jest.mock('../../../../src/worker/plugins/run')

const testElements: any = ['element1', 'element2']

// @ts-expect-error TODO: Add project_id
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
                    cdpLegacyOnEvent: true,
                },
                actionMatcher: {
                    match: jest.fn().mockReturnValue(['action1', 'action2']),
                },
                hookCannon: {
                    findAndFireHooks: jest.fn().mockResolvedValue(true),
                },
            },
        }
    })

    it('does action matching and fires webhooks', async () => {
        await processWebhooksStep(ingestionEvent, runner.hub.actionMatcher, runner.hub.hookCannon)

        expect(runner.hub.actionMatcher.match).toHaveBeenCalled()
        expect(runner.hub.hookCannon.findAndFireHooks).toHaveBeenCalledWith(ingestionEvent, ['action1', 'action2'])
    })
})
