import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Person } from '../../../../src/types'
import { UUIDT } from '../../../../src/utils/utils'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/3-processPersonsStep'
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

const person: Person = {
    id: 123,
    team_id: 2,
    properties: {},
    is_user_id: 0,
    is_identified: true,
    uuid: new UUIDT().toString(),
    properties_last_updated_at: {},
    properties_last_operation: {},
    created_at: DateTime.now(),
    version: 0,
}

describe('processPersonsStep()', () => {
    let runner: any

    beforeEach(() => {
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
                db: 'hub.db',
                statsd: 'hub.statsd',
                personManager: 'hub.personManager',
            },
        }

        jest.mocked(updatePersonState).mockResolvedValue(person)
    })

    it('forwards event to `prepareEventStep`', async () => {
        const response = await processPersonsStep(runner, pluginEvent, person)

        expect(response).toEqual(['prepareEventStep', pluginEvent, person])
    })

    it('re-normalizes the event with properties set by plugins', async () => {
        const updatedPerson = {
            ...person,
            properties: { personProp: 'value ' },
        }
        const event = {
            ...pluginEvent,
            properties: {
                $browser: 'Chrome',
            },
            $set: {
                someProp: 'value',
            },
        }
        jest.mocked(updatePersonState).mockResolvedValue(updatedPerson)

        const response = await processPersonsStep(runner, event, person)

        expect(response).toEqual([
            'prepareEventStep',
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
            updatedPerson,
        ])
    })

    it('updates person', async () => {
        const updatedPerson = {
            ...person,
            properties: { personProp: 'value ' },
        }
        jest.mocked(updatePersonState).mockResolvedValue(updatedPerson)

        const response = await processPersonsStep(runner, pluginEvent, person)

        expect(updatePersonState).toHaveBeenCalledWith(
            pluginEvent,
            2,
            'my_id',
            expect.any(DateTime),
            'hub.db',
            'hub.statsd',
            'hub.personManager',
            person
        )
        expect(response).toEqual(['prepareEventStep', pluginEvent, updatedPerson])
    })
})
