import { PluginEvent } from '@posthog/plugin-scaffold'

import { Person } from '../../../../src/types'
import { pluginsProcessEventStep } from '../../../../src/worker/ingestion/event-pipeline/2-pluginsProcessEventStep'
import { runProcessEvent } from '../../../../src/worker/plugins/run'

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

const person = {
    id: 123,
} as any as Person

describe('pluginsProcessEventStep()', () => {
    let runner: any

    beforeEach(() => {
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
                statsd: {
                    increment: jest.fn(),
                    timing: jest.fn(),
                },
            },
        }
    })

    it('forwards processed plugin event to `processPersonsStep`', async () => {
        const processedEvent = { ...pluginEvent, event: 'processed' }
        jest.mocked(runProcessEvent).mockResolvedValue(processedEvent)

        const response = await pluginsProcessEventStep(runner, pluginEvent, person)

        expect(response).toEqual(['processPersonsStep', processedEvent, person])
    })

    it('automatically forwards `$snapshot` events', async () => {
        const event = { ...pluginEvent, event: '$snapshot' }

        const response = await pluginsProcessEventStep(runner, event, person)

        expect(runProcessEvent).not.toHaveBeenCalled()
        expect(response).toEqual(['processPersonsStep', event, person])
    })

    it('does not forward but counts dropped events by plugins', async () => {
        jest.mocked(runProcessEvent).mockResolvedValue(null)

        const response = await pluginsProcessEventStep(runner, pluginEvent, person)

        expect(response).toEqual(null)
        expect(runner.hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.dropped_event', { teamID: '2' })
    })
})
