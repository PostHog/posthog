import { PluginEvent } from '@posthog/plugin-scaffold'

import { pluginsProcessEventStep } from '../../../../src/worker/ingestion/event-pipeline/2-pluginsProcessEventStep'
import { LazyPersonContainer } from '../../../../src/worker/ingestion/lazy-person-container'
import { runProcessEvent } from '../../../../src/worker/plugins/run'
import { createTaskRunner } from '../../../../src/worker/worker'

jest.mock('../../../../src/worker/plugins/run')

const pluginEvent: PluginEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 2,
    now: '2020-02-23T02:15:00Z',
    timestamp: '2020-02-23T02:15:00Z',
    event: 'default event',
    properties: {},
    uuid: '017ef865-19da-0000-3b60-1506093bf40f',
}

describe('pluginsProcessEventStep()', () => {
    let runner: any
    let taskRunner: any
    let hub: any
    let personContainer: any

    beforeEach(() => {
        hub = {
            statsd: {
                increment: jest.fn(),
                timing: jest.fn(),
            },
        }
        taskRunner = createTaskRunner(hub)
        runner = {
            nextStep: (...args: any[]) => args,
            piscina: {
                run: ({ task, args }: { task: string; args: any }) => taskRunner({ task, args }),
            },
            hub: hub,
        }
        personContainer = new LazyPersonContainer(2, 'my_id', runner.hub)
    })

    it('forwards processed plugin event to `processPersonsStep`', async () => {
        const processedEvent = { ...pluginEvent, event: 'processed' }
        jest.mocked(runProcessEvent).mockResolvedValue(processedEvent)

        const response = await pluginsProcessEventStep(runner, pluginEvent, personContainer)

        expect(response).toEqual(['processPersonsStep', processedEvent, personContainer])
    })

    it('automatically forwards `$snapshot` events', async () => {
        const event = { ...pluginEvent, event: '$snapshot' }

        const response = await pluginsProcessEventStep(runner, event, personContainer)

        expect(runProcessEvent).not.toHaveBeenCalled()
        expect(response).toEqual(['processPersonsStep', event, personContainer])
    })

    it('does not forward but counts dropped events by plugins', async () => {
        jest.mocked(runProcessEvent).mockResolvedValue(null)

        const response = await pluginsProcessEventStep(runner, pluginEvent, personContainer)

        expect(response).toEqual(null)
        expect(runner.hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.dropped_event', { teamID: '2' })
    })
})
