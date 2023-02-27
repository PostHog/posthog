import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { LazyPersonContainer } from '../../../../src/worker/ingestion/lazy-person-container'
import { updatePersonState } from '../../../../src/worker/ingestion/person-state'

jest.mock('../../../../src/utils/status')
jest.mock('../../../../src/worker/ingestion/person-state')

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

describe('processPersonsStep()', () => {
    let runner: any
    let personContainer: any

    beforeEach(() => {
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
                db: 'hub.db',
                statsd: 'hub.statsd',
                personManager: 'hub.personManager',
                kafkaProducer: {
                    producer: {
                        send: jest.fn(),
                    },
                },
            },
            poEEmbraceJoin: true,
        }
        personContainer = new LazyPersonContainer(2, 'my_id', runner.hub)

        jest.mocked(updatePersonState).mockResolvedValue(personContainer)
    })

    it('forwards event to `prepareEventStep`', async () => {
        const response = await processPersonsStep(runner, pluginEvent, personContainer)

        expect(response).toEqual([pluginEvent, personContainer])
        expect(jest.mocked(updatePersonState)).toHaveBeenCalled()
    })

    it('re-normalizes the event with properties set by plugins', async () => {
        const event = {
            ...pluginEvent,
            properties: {
                $browser: 'Chrome',
            },
            $set: {
                someProp: 'value',
            },
        }
        const updatedContainer = new LazyPersonContainer(2, 'my_id2', runner.hub)
        jest.mocked(updatePersonState).mockResolvedValue(updatedContainer)

        const response = await processPersonsStep(runner, event, personContainer)

        expect(response).toEqual([
            {
                ...event,
                properties: {
                    $browser: 'Chrome',
                    $set: {
                        someProp: 'value',
                    },
                    $set_once: {
                        $initial_browser: 'Chrome',
                    },
                },
            },
            updatedContainer,
        ])
    })

    it('updates person', async () => {
        const updatedContainer = new LazyPersonContainer(2, 'my_id2', runner.hub)
        jest.mocked(updatePersonState).mockResolvedValue(updatedContainer)

        const response = await processPersonsStep(runner, pluginEvent, personContainer)

        expect(updatePersonState).toHaveBeenCalledWith(
            pluginEvent,
            2,
            'my_id',
            expect.any(DateTime),
            'hub.db',
            'hub.statsd',
            'hub.personManager',
            personContainer,
            runner.poEEmbraceJoin
        )
        expect(response).toEqual([pluginEvent, updatedContainer])
    })
})
