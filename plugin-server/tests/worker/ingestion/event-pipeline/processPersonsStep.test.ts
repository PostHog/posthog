import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { createOrganization, createTeam, fetchPostgresPersons, resetTestDatabase } from '../../../helpers/sql'

describe.each([[true], [false]])('processPersonsStep()', (poEEmbraceJoin) => {
    let runner: any
    let hub: Hub
    let closeHub: () => Promise<void>

    let uuid: string
    let teamId: number
    let pluginEvent: PluginEvent

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub()
        runner = {
            nextStep: (...args: any[]) => args,
            hub: hub,
            poEEmbraceJoin: poEEmbraceJoin,
        }
        const organizationId = await createOrganization(runner.hub.db.postgres)
        teamId = await createTeam(runner.hub.db.postgres, organizationId)
        uuid = new UUIDT().toString()

        pluginEvent = {
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
            },
            uuid: uuid,
        }
    })
    afterEach(async () => {
        await closeHub?.()
    })

    it('creates person', async () => {
        const [resEvent, resPerson] = await processPersonsStep(runner, pluginEvent)

        expect(resEvent).toEqual(pluginEvent)
        expect(resPerson).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: expect.any(String),
                properties: { a: 5, $creator_event_uuid: expect.any(String) },
                version: 0,
                is_identified: false,
                team_id: teamId,
            })
        )

        // Check PG state
        const persons = await fetchPostgresPersons(runner.hub.db, teamId)
        expect(persons).toEqual([resPerson])
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
        const [resEvent, resPerson] = await processPersonsStep(runner, event)

        expect(resEvent).toEqual({
            ...event,
            properties: {
                $browser: 'Chrome',
                $set: {
                    someProp: 'value',
                    $browser: 'Chrome',
                },
                $set_once: {
                    $initial_browser: 'Chrome',
                },
            },
        })
        expect(resPerson).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: expect.any(String),
                properties: {
                    $initial_browser: 'Chrome',
                    someProp: 'value',
                    $creator_event_uuid: expect.any(String),
                    $browser: 'Chrome',
                },
                version: 0,
                is_identified: false,
            })
        )

        // Check PG state
        const persons = await fetchPostgresPersons(runner.hub.db, teamId)
        expect(persons).toEqual([resPerson])
    })
})
