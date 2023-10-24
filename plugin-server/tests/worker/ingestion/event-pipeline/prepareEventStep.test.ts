import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Hub, Person, Team } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/prepareEventStep'
import { resetTestDatabase } from '../../../helpers/sql'

jest.mock('../../../../src/utils/status')

const pluginEvent: PluginEvent = {
    distinct_id: 'my_id',
    ip: null,
    site_url: 'http://localhost',
    team_id: 2,
    now: '2020-02-23T02:15:00Z',
    timestamp: '2020-02-23T02:15:00Z',
    event: 'default event',
    properties: {
        $ip: '127.0.0.1',
    },
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

const teamTwo: Team = {
    id: 2,
    uuid: 'af95d312-1a0a-4208-b80f-562ddafc9bcd',
    organization_id: '66f3f7bf-44e2-45dd-9901-5dbd93744e3a',
    name: 'testTeam',
    anonymize_ips: false,
    api_token: 'token',
    slack_incoming_webhook: '',
    session_recording_opt_in: false,
    ingested_event: true,
}

describe('prepareEventStep()', () => {
    let runner: any
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub()

        // :KLUDGE: We test below whether kafka messages are produced, so make sure the person exists beforehand.
        await hub.db.createPerson(person.created_at, {}, {}, {}, pluginEvent.team_id, null, false, person.uuid, [
            'my_id',
        ])
        hub.db.kafkaProducer!.queueMessage = jest.fn()

        // eslint-disable-next-line @typescript-eslint/require-await
        hub.eventsProcessor.teamManager.fetchTeam = jest.fn(async (teamId) => {
            return teamId === 2 ? teamTwo : null
        })

        runner = {
            nextStep: (...args: any[]) => args,
            hub,
        }
    })

    afterEach(async () => {
        await closeHub()
    })

    it('goes to `createEventStep` for normal events', async () => {
        const response = await prepareEventStep(runner, pluginEvent)

        expect(response).toEqual({
            distinctId: 'my_id',
            event: 'default event',
            eventUuid: '017ef865-19da-0000-3b60-1506093bf40f',
            properties: {
                $ip: '127.0.0.1',
            },
            teamId: 2,
            timestamp: '2020-02-23T02:15:00.000Z',
        })
        expect(hub.db.kafkaProducer!.queueMessage).not.toHaveBeenCalled()
    })

    it('scrubs IPs when team.anonymize_ips=true', async () => {
        jest.mocked(runner.hub.eventsProcessor.teamManager.fetchTeam).mockReturnValue({
            ...teamTwo,
            anonymize_ips: true,
        })
        const response = await prepareEventStep(runner, pluginEvent)

        expect(response).toEqual({
            distinctId: 'my_id',
            event: 'default event',
            eventUuid: '017ef865-19da-0000-3b60-1506093bf40f',
            properties: {},
            teamId: 2,
            timestamp: '2020-02-23T02:15:00.000Z',
        })
        expect(hub.db.kafkaProducer!.queueMessage).not.toHaveBeenCalled()
    })

    // Tests combo of prepareEvent + createEvent
    it('extracts elements_chain from properties', async () => {
        const event: PluginEvent = { ...pluginEvent, ip: null, properties: { $elements_chain: 'random string', a: 1 } }
        const preppedEvent = await prepareEventStep(runner, event)
        const [chEvent, _] = await runner.hub.eventsProcessor.createEvent(preppedEvent, person)

        expect(chEvent.elements_chain).toEqual('random string')
        expect(chEvent.properties).toEqual('{"a":1}')
    })
    // Tests combo of prepareEvent + createEvent
    it('uses elements_chain if both elements and elements_chain are present', async () => {
        const event: PluginEvent = {
            ...pluginEvent,
            ip: null,
            properties: {
                $elements_chain: 'random string',
                a: 1,
                $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
            },
        }
        const preppedEvent = await prepareEventStep(runner, event)
        const [chEvent, _] = await runner.hub.eventsProcessor.createEvent(preppedEvent, person)

        expect(chEvent.elements_chain).toEqual('random string')
        expect(chEvent.properties).toEqual('{"a":1}')
    })

    // Tests combo of prepareEvent + createEvent
    it('processes elements correctly', async () => {
        const event: PluginEvent = {
            ...pluginEvent,
            ip: null,
            properties: { a: 1, $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }] },
        }
        const preppedEvent = await prepareEventStep(runner, event)
        const [chEvent, _] = await runner.hub.eventsProcessor.createEvent(preppedEvent, person)

        expect(chEvent.elements_chain).toEqual('div:nth-child="1"nth-of-type="2"text="text"')
        expect(chEvent.properties).toEqual('{"a":1}')
    })
})
