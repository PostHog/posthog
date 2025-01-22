import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import fetch from 'node-fetch'

import { Hook, Hub } from '../../../../src/types'
import { closeHub, createHub } from '../../../../src/utils/db/hub'
import { PostgresUse } from '../../../../src/utils/db/postgres'
import { convertToPostIngestionEvent } from '../../../../src/utils/event'
import { UUIDT } from '../../../../src/utils/utils'
import { processOnEventStep } from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { EventsProcessor } from '../../../../src/worker/ingestion/process-event'
import { setupPlugins } from '../../../../src/worker/plugins/setup'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../../helpers/clickhouse'
import { commonUserId } from '../../../helpers/plugins'
import { insertRow, resetTestDatabase } from '../../../helpers/sql'

jest.mock('../../../../src/utils/status')

describe('Event Pipeline integration test', () => {
    let hub: Hub

    const ingestEvent = async (event: PluginEvent) => {
        const runner = new EventPipelineRunner(hub, event, new EventsProcessor(hub))
        const result = await runner.runEventPipeline(event)
        const postIngestionEvent = convertToPostIngestionEvent(result.args[0])
        return Promise.all([processOnEventStep(runner.hub, postIngestionEvent)])
    }

    beforeEach(async () => {
        await resetTestDatabase()
        await resetTestDatabaseClickhouse()
        process.env.SITE_URL = 'https://example.com'
        hub = await createHub()

        jest.spyOn(hub.db, 'fetchPerson')
        jest.spyOn(hub.db, 'createPerson')
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('handles plugins setting properties', async () => {
        await resetTestDatabase(`
            function processEvent (event) {
                event.properties = {
                    ...event.properties,
                    $browser: 'Chrome',
                    processed: 'hell yes'
                }
                event.$set = {
                    ...event.$set,
                    personProp: 'value'
                }
                return event
            }
        `)
        await setupPlugins(hub)

        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            $set: { personProp: 1, anotherValue: 2 },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: 2,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }

        await ingestEvent(event)

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        const persons = await delayUntilEventIngested(() => hub.db.fetchPersons())

        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: event.uuid,
                event: 'xyz',
                team_id: 2,
                timestamp: DateTime.fromISO(event.timestamp!, { zone: 'utc' }),
                // :KLUDGE: Ignore properties like $plugins_succeeded, etc
                properties: expect.objectContaining({
                    foo: 'bar',
                    $browser: 'Chrome',
                    processed: 'hell yes',
                    $set: {
                        personProp: 'value',
                        anotherValue: 2,
                        $browser: 'Chrome',
                    },
                    $set_once: {
                        $initial_browser: 'Chrome',
                    },
                }),
            })
        )

        expect(persons.length).toEqual(1)
        expect(persons[0].version).toEqual(0)
        expect(persons[0].properties).toEqual({
            $creator_event_uuid: event.uuid,
            $initial_browser: 'Chrome',
            $browser: 'Chrome',
            personProp: 'value',
            anotherValue: 2,
        })
    })

    it('single postgres action per run to create or load person', async () => {
        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: 2,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }

        await new EventPipelineRunner(hub, event, new EventsProcessor(hub)).runEventPipeline(event)

        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1) // we query before creating
        expect(hub.db.createPerson).toHaveBeenCalledTimes(1)

        // second time single fetch
        await new EventPipelineRunner(hub, event, new EventsProcessor(hub)).runEventPipeline(event)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(2)
    })
})
