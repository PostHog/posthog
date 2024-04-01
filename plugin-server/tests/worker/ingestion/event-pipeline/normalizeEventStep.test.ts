import { DateTime } from 'luxon'

import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { normalizeEventStep } from '../../../../src/worker/ingestion/event-pipeline/normalizeEventStep'
import { createOrganization, createTeam, resetTestDatabase } from '../../../helpers/sql'

describe.each([[true], [false]])('normalizeEventStep()', () => {
    it('normalizes the event with properties set by plugins', async () => {
        await resetTestDatabase()
        const [hub, _] = await createHub()
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
            },
            $set: {
                someProp: 'value',
            },
            uuid: uuid,
        }

        const [resEvent, timestamp] = normalizeEventStep(event)

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
})
