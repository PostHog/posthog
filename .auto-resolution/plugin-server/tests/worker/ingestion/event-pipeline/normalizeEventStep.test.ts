import { DateTime } from 'luxon'

import { createHub } from '../../../../src/utils/db/hub'
import { parseJSON } from '../../../../src/utils/json-parse'
import { UUIDT } from '../../../../src/utils/utils'
import { normalizeEventStep } from '../../../../src/worker/ingestion/event-pipeline/normalizeEventStep'
import { createOrganization, createTeam, resetTestDatabase } from '../../../helpers/sql'

// A simple deep copy to ensure we aren't comparing an event object with itself below.
function copy(a: any) {
    return parseJSON(JSON.stringify(a))
}

describe('normalizeEventStep()', () => {
    it('normalizes the event with properties set by plugins', async () => {
        await resetTestDatabase()
        const hub = await createHub()
        const organizationId = await createOrganization(hub.db.postgres)
        const teamId = await createTeam(hub.db.postgres, organizationId)
        const uuid = new UUIDT().toString()
        const event = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: teamId,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'default event',
            properties: {
                $set: {
                    a: 5,
                },
                $browser: 'Chrome',
                $process_person_profile: true, // This is dropped, as it is implied
            },
            $set: {
                someProp: 'value',
            },
            uuid: uuid,
        }

        const processPerson = true
        const [resEvent, timestamp] = await normalizeEventStep(copy(event), processPerson)

        expect(resEvent).toEqual({
            ...event,
            properties: {
                $browser: 'Chrome',
                $set: {
                    someProp: 'value',
                    a: 5,
                    $browser: 'Chrome',
                },
                $set_once: {
                    $initial_browser: 'Chrome',
                },
            },
        })

        expect(timestamp).toEqual(DateTime.fromISO(event.timestamp!, { zone: 'utc' }))
    })

    it('replaces null byte with unicode replacement character in distinct_id', async () => {
        await resetTestDatabase()
        const hub = await createHub()
        const organizationId = await createOrganization(hub.db.postgres)
        const teamId = await createTeam(hub.db.postgres, organizationId)
        const uuid = new UUIDT().toString()
        const event = {
            distinct_id: '\u0000foo',
            ip: null,
            site_url: 'http://localhost',
            team_id: teamId,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'default event',
            uuid: uuid,
        }

        const processPerson = true
        const [resEvent, timestamp] = await normalizeEventStep(copy(event), processPerson)

        expect(resEvent).toEqual({
            ...event,
            distinct_id: '\uFFFDfoo',
            properties: {},
        })

        expect(timestamp).toEqual(DateTime.fromISO(event.timestamp!, { zone: 'utc' }))
    })

    it('normalizes $process_person_profile=false events by dropping $set and related', async () => {
        await resetTestDatabase()
        const hub = await createHub()
        const organizationId = await createOrganization(hub.db.postgres)
        const teamId = await createTeam(hub.db.postgres, organizationId)
        const uuid = new UUIDT().toString()
        const event = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: teamId,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'default event',
            properties: {
                $set: {
                    a: 5,
                },
                $set_once: {
                    b: 10,
                },
                $unset: ['c'],
                $browser: 'Chrome',
            },
            $set: {
                someProp: 'value',
            },
            $set_once: {
                foo: 'bar',
            },
            uuid: uuid,
        }

        const processPerson = false
        const [resEvent, timestamp] = await normalizeEventStep(copy(event), processPerson)

        // These should be gone in the comparison below.
        delete (event as any)['$set']
        delete (event as any)['$set_once']

        expect(resEvent).toEqual({
            ...event,
            properties: {
                $browser: 'Chrome',
                $process_person_profile: false,
            },
        })

        expect(timestamp).toEqual(DateTime.fromISO(event.timestamp!, { zone: 'utc' }))
    })
})
