import { IngestionEvent } from '../../../../src/types'
import { convertToProcessedPluginEvent } from '../../../../src/utils/event'
import { runAsyncHandlersStep } from '../../../../src/worker/ingestion/event-pipeline/6-runAsyncHandlersStep'
import { runOnEvent, runOnSnapshot } from '../../../../src/worker/plugins/run'

jest.mock('../../../../src/worker/plugins/run')

const testPerson: any = { id: 'testid' }
const testElements: any = ['element1', 'element2']
const ingestionEvent: IngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00Z',
    event: '$pageview',
    properties: {},
    elementsList: testElements,
}
const snapshotEvent = {
    ...ingestionEvent,
    event: '$snapshot',
}

describe('runAsyncHandlersStep()', () => {
    let runner: any
    let personContainer: any

    beforeEach(() => {
        personContainer = {
            get: jest.fn().mockResolvedValue(testPerson),
        }
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
                capabilities: {
                    processAsyncHandlers: true,
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
        const response = await runAsyncHandlersStep(runner, ingestionEvent, personContainer)

        expect(response).toEqual(null)
    })

    it('does action matching and fires webhooks', async () => {
        await runAsyncHandlersStep(runner, ingestionEvent, personContainer)

        expect(runner.hub.actionMatcher.match).toHaveBeenCalled()
        expect(runner.hub.hookCannon.findAndFireHooks).toHaveBeenCalledWith(ingestionEvent, personContainer, [
            'action1',
            'action2',
        ])
    })

    it('calls onEvent plugin methods', async () => {
        await runAsyncHandlersStep(runner, ingestionEvent, personContainer)

        expect(runOnEvent).toHaveBeenCalledWith(runner.hub, convertToProcessedPluginEvent(ingestionEvent))
        expect(runOnSnapshot).not.toHaveBeenCalled()
    })

    it('still calls onEvent if actions lookup fails', async () => {
        const error = new Error('Event matching failed')
        jest.mocked(runner.hub.actionMatcher.match).mockRejectedValue(error)

        await expect(runAsyncHandlersStep(runner, ingestionEvent, personContainer)).rejects.toThrow(error)

        expect(runOnEvent).toHaveBeenCalledWith(runner.hub, convertToProcessedPluginEvent(ingestionEvent))
    })

    it('stops processing if not capabilities.processAsyncHandlers', async () => {
        runner.hub.capabilities.processAsyncHandlers = false

        const result = await runAsyncHandlersStep(runner, ingestionEvent, personContainer)

        expect(result).toEqual(null)
        expect(runOnSnapshot).not.toHaveBeenCalled()
        expect(runOnEvent).not.toHaveBeenCalled()
    })

    describe('$snapshot events', () => {
        it('does not do action matching or webhook firing', async () => {
            await runAsyncHandlersStep(runner, snapshotEvent, personContainer)

            expect(runner.hub.actionMatcher.match).not.toHaveBeenCalled()
            expect(runner.hub.hookCannon.findAndFireHooks).not.toHaveBeenCalled()
        })

        it('calls only onSnapshot plugin methods', async () => {
            await runAsyncHandlersStep(runner, snapshotEvent, personContainer)

            expect(runOnSnapshot).toHaveBeenCalledWith(runner.hub, convertToProcessedPluginEvent(snapshotEvent))
            expect(runOnEvent).not.toHaveBeenCalled()
        })
    })
})
