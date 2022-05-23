import { PreIngestionEvent } from '../../../../src/types'
import { convertToProcessedPluginEvent } from '../../../../src/utils/event'
import { runAsyncHandlersStep } from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { runOnAction, runOnEvent, runOnSnapshot } from '../../../../src/worker/plugins/run'

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
const snapshotEvent = {
    ...preIngestionEvent,
    event: '$snapshot',
}

const testPerson: any = { id: 'testid' }
const testElements: any = ['element1', 'element2']

describe('runAsyncHandlersStep()', () => {
    let runner: any

    beforeEach(() => {
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
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
        const response = await runAsyncHandlersStep(runner, preIngestionEvent, testPerson, testElements)

        expect(response).toEqual(null)
    })

    it('does action matching and fires webhooks', async () => {
        await runAsyncHandlersStep(runner, preIngestionEvent, testPerson, testElements)

        expect(runner.hub.actionMatcher.match).toHaveBeenCalled()
        expect(runner.hub.hookCannon.findAndFireHooks).toHaveBeenCalledWith(preIngestionEvent, testPerson, [
            'action1',
            'action2',
        ])
    })

    it('calls onEvent and onAction plugin methods', async () => {
        await runAsyncHandlersStep(runner, preIngestionEvent, testPerson, testElements)

        expect(runOnEvent).toHaveBeenCalledWith(runner.hub, convertToProcessedPluginEvent(preIngestionEvent))
        expect(runOnAction).toHaveBeenCalledWith(
            runner.hub,
            'action1',
            convertToProcessedPluginEvent(preIngestionEvent)
        )
        expect(runOnAction).toHaveBeenCalledWith(
            runner.hub,
            'action2',
            convertToProcessedPluginEvent(preIngestionEvent)
        )
        expect(runOnSnapshot).not.toHaveBeenCalled()
    })

    it('still calls onEvent if actions lookup fails', async () => {
        const error = new Error('Event matching failed')
        jest.mocked(runner.hub.actionMatcher.match).mockRejectedValue(error)

        await expect(runAsyncHandlersStep(runner, preIngestionEvent, testPerson, testElements)).rejects.toThrow(error)

        expect(runOnEvent).toHaveBeenCalledWith(runner.hub, convertToProcessedPluginEvent(preIngestionEvent))
        expect(runOnAction).not.toHaveBeenCalled()
    })

    describe('$snapshot events', () => {
        it('does not do action matching or webhook firing', async () => {
            await runAsyncHandlersStep(runner, snapshotEvent, testPerson, testElements)

            expect(runner.hub.actionMatcher.match).not.toHaveBeenCalled()
            expect(runner.hub.hookCannon.findAndFireHooks).not.toHaveBeenCalled()
        })

        it('calls only onSnapshot plugin methods', async () => {
            await runAsyncHandlersStep(runner, snapshotEvent, testPerson, testElements)

            expect(runOnSnapshot).toHaveBeenCalledWith(runner.hub, convertToProcessedPluginEvent(snapshotEvent))
            expect(runOnEvent).not.toHaveBeenCalled()
            expect(runOnAction).not.toHaveBeenCalled()
        })
    })
})
