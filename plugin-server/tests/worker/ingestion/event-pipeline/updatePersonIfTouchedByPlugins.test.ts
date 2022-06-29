import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Person } from '../../../../src/types'
import { UUIDT } from '../../../../src/utils/utils'
import { ForwardedPersonData } from '../../../../src/worker/ingestion/event-pipeline/2-processPersonsStep'
import { updatePersonIfTouchedByPlugins } from '../../../../src/worker/ingestion/event-pipeline/4-updatePersonIfTouchedByPlugins'
import { updatePropertiesPersonState } from '../../../../src/worker/ingestion/person-state'

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

const updatedPerson = {
    ...person,
    version: 1,
}

const forwardedPersonData: ForwardedPersonData = {
    person,
    personUpdateProperties: {},
}

describe('updatePersonIfTouchedByPlugins()', () => {
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

        jest.mocked(updatePropertiesPersonState).mockResolvedValue(updatedPerson)
    })

    it('forwards to `prepareEventStep`', async () => {
        const response = await updatePersonIfTouchedByPlugins(runner, pluginEvent, forwardedPersonData)

        expect(response).toEqual(['prepareEventStep', pluginEvent, person])
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

        const response = await updatePersonIfTouchedByPlugins(runner, event, forwardedPersonData)

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

    it('does not update person by default', async () => {
        await updatePersonIfTouchedByPlugins(runner, pluginEvent, forwardedPersonData)

        expect(updatePropertiesPersonState).not.toHaveBeenCalled()
    })

    it('does not update person if properties did not change by plugins', async () => {
        const event = {
            ...pluginEvent,
            properties: {
                $set: {
                    someProp: 'value',
                },
            },
        }

        await updatePersonIfTouchedByPlugins(runner, pluginEvent, {
            person,
            personUpdateProperties: {
                $set: event.properties.$set,
            },
        })

        expect(updatePropertiesPersonState).not.toHaveBeenCalled()
    })

    it('updates person if $set property was changed by plugins', async () => {
        const event = {
            ...pluginEvent,
            properties: {
                $set: {
                    someProp: 'newValue',
                },
            },
        }

        const response = await updatePersonIfTouchedByPlugins(runner, event, {
            person,
            personUpdateProperties: {
                $set: {
                    someProp: 'oldValue',
                },
            },
        })

        expect(updatePropertiesPersonState).toHaveBeenCalledWith(
            event,
            2,
            'my_id',
            expect.any(DateTime),
            'hub.db',
            'hub.statsd',
            'hub.personManager',
            person
        )
        expect(response).toEqual(['prepareEventStep', event, updatedPerson])
    })

    it.only('updates person if $set_once property was changed by plugins', async () => {
        const response = await updatePersonIfTouchedByPlugins(runner, pluginEvent, {
            person,
            personUpdateProperties: {
                $set_once: {
                    someProp: 'newValue',
                },
            },
        })

        expect(updatePropertiesPersonState).toHaveBeenCalledWith(
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

    it('updates person if $unset property was changed by plugins', async () => {
        const event = {
            ...pluginEvent,
            properties: {
                $unset: ['some_property'],
            },
        }

        const response = await updatePersonIfTouchedByPlugins(runner, event, forwardedPersonData)

        expect(updatePropertiesPersonState).toHaveBeenCalledWith(
            event,
            2,
            'my_id',
            expect.any(DateTime),
            'hub.db',
            'hub.statsd',
            'hub.personManager',
            person
        )
        expect(response).toEqual(['prepareEventStep', event, updatedPerson])
    })
})
