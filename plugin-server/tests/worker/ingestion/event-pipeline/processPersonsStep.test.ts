import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Hub } from '../../../../src/types'
import { closeHub, createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { normalizeEventStep } from '../../../../src/worker/ingestion/event-pipeline/normalizeEventStep'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { EventsProcessor } from '../../../../src/worker/ingestion/process-event'
import { createOrganization, createTeam, fetchPostgresPersons, resetTestDatabase } from '../../../helpers/sql'

describe('processPersonsStep()', () => {
    let runner: Pick<EventPipelineRunner, 'hub' | 'eventsProcessor'>
    let hub: Hub

    let uuid: string
    let teamId: number
    let pluginEvent: PluginEvent
    let timestamp: DateTime

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        runner = {
            hub: hub,
            eventsProcessor: new EventsProcessor(hub),
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
        timestamp = DateTime.fromISO(pluginEvent.timestamp!)
    })
    afterEach(async () => {
        await closeHub(hub)
    })

    it('creates person', async () => {
        const processPerson = true
        const [resEvent, resPerson] = await processPersonsStep(runner, pluginEvent, timestamp, processPerson)

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

    it('creates event with normalized properties set by plugins', async () => {
        const event = {
            ...pluginEvent,
            properties: {
                $browser: 'Chrome',
            },
            $set: {
                someProp: 'value',
            },
        }

        const processPerson = true
        const [normalizedEvent, timestamp] = await normalizeEventStep(event, processPerson)
        const [resEvent, resPerson] = await processPersonsStep(runner, normalizedEvent, timestamp, processPerson)

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

    it('only updates initial campaign params set in the first event', async () => {
        const event1 = {
            ...pluginEvent,
            properties: {
                utm_source: 'foo',
            },
        }
        const event2 = {
            ...pluginEvent,
            properties: {
                utm_medium: 'bar',
            },
        }

        const processPerson = true
        const [normalizedEvent1, timestamp1] = await normalizeEventStep(event1, processPerson)
        await processPersonsStep(runner, normalizedEvent1, timestamp1, processPerson)
        const [normalizedEvent2, timestamp2] = await normalizeEventStep(event2, processPerson)
        const [_, resPerson2] = await processPersonsStep(runner, normalizedEvent2, timestamp2, processPerson)

        expect(resPerson2).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: expect.any(String),
                properties: {
                    $creator_event_uuid: expect.any(String),
                    utm_source: 'foo',
                    utm_medium: 'bar',
                    $initial_utm_source: 'foo',
                },
                version: 1,
            })
        )

        // Check PG state
        const persons = await fetchPostgresPersons(runner.hub.db, teamId)
        expect(persons).toEqual([resPerson2])
    })

    it('sets initial campaign params when upgrading user from anonymous to identified', async () => {
        const event1 = {
            ...pluginEvent,
            properties: {
                utm_source: 'foo',
            },
        }
        // posthog-js stores initial campaign params for anonymous users, and sends them if the user becomes identified
        const event2 = {
            ...pluginEvent,
            properties: {
                utm_source: 'bar',
                $set_once: {
                    $initial_utm_source: 'foo',
                },
            },
        }

        const processPerson1 = false
        const [normalizedEvent1, timestamp1] = await normalizeEventStep(event1, processPerson1)
        await processPersonsStep(runner, normalizedEvent1, timestamp1, processPerson1)
        const processPerson2 = true
        const [normalizedEvent2, timestamp2] = await normalizeEventStep(event2, processPerson2)
        const [_, resPerson2] = await processPersonsStep(runner, normalizedEvent2, timestamp2, processPerson2)

        expect(resPerson2).toEqual(
            expect.objectContaining({
                id: expect.any(Number),
                uuid: expect.any(String),
                properties: {
                    $creator_event_uuid: expect.any(String),
                    $initial_utm_source: 'foo',
                    utm_source: 'bar',
                },
                version: 0,
            })
        )

        // Check PG state
        const persons = await fetchPostgresPersons(runner.hub.db, teamId)
        expect(persons).toEqual([resPerson2])
    })
})
