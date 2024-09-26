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
                properties: {
                    a: 5,
                    $creator_event_uuid: expect.any(String),
                    $initial_dclid: null,
                    $initial_fbclid: null,
                    $initial_gad_source: null,
                    $initial_gbraid: null,
                    $initial_gclid: null,
                    $initial_gclsrc: null,
                    $initial_igshid: null,
                    $initial_li_fat_id: null,
                    $initial_mc_cid: null,
                    $initial_msclkid: null,
                    $initial_rdt_cid: null,
                    $initial_ttclid: null,
                    $initial_twclid: null,
                    $initial_utm_campaign: null,
                    $initial_utm_content: null,
                    $initial_utm_medium: null,
                    $initial_utm_name: null,
                    $initial_utm_source: null,
                    $initial_utm_term: null,
                    $initial_wbraid: null,
                },
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
                    $initial_dclid: null,
                    $initial_fbclid: null,
                    $initial_gad_source: null,
                    $initial_gbraid: null,
                    $initial_gclid: null,
                    $initial_gclsrc: null,
                    $initial_igshid: null,
                    $initial_li_fat_id: null,
                    $initial_mc_cid: null,
                    $initial_msclkid: null,
                    $initial_rdt_cid: null,
                    $initial_ttclid: null,
                    $initial_twclid: null,
                    $initial_utm_campaign: null,
                    $initial_utm_content: null,
                    $initial_utm_medium: null,
                    $initial_utm_name: null,
                    $initial_utm_source: null,
                    $initial_utm_term: null,
                    $initial_wbraid: null,
                },
                version: 0,
                is_identified: false,
            })
        )

        // Check PG state
        const persons = await fetchPostgresPersons(runner.hub.db, teamId)
        expect(persons).toEqual([resPerson])
    })

    it('only sets initial campaign params from the event that creates the Person', async () => {
        const event1 = {
            ...pluginEvent,
            properties: {
                utm_source: 'foo',
                $browser: 'Chrome',
            },
        }
        const event2 = {
            ...pluginEvent,
            properties: {
                utm_medium: 'bar',
                $browser: 'Chrome',
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
                    $initial_browser: 'Chrome',
                    $browser: 'Chrome',
                    $initial_dclid: null,
                    $initial_fbclid: null,
                    $initial_gad_source: null,
                    $initial_gbraid: null,
                    $initial_gclid: null,
                    $initial_gclsrc: null,
                    $initial_igshid: null,
                    $initial_li_fat_id: null,
                    $initial_mc_cid: null,
                    $initial_msclkid: null,
                    $initial_rdt_cid: null,
                    $initial_ttclid: null,
                    $initial_twclid: null,
                    $initial_utm_campaign: null,
                    $initial_utm_content: null,
                    $initial_utm_medium: null,
                    $initial_utm_name: null,
                    $initial_utm_source: 'foo',
                    $initial_utm_term: null,
                    $initial_wbraid: null,
                },
                version: 1,
            })
        )

        // Check PG state
        const persons = await fetchPostgresPersons(runner.hub.db, teamId)
        expect(persons).toEqual([resPerson2])
    })

    // fails at utm_source is set from the upgrading event
    it('sets initial campaign params when upgrading user from anonymous to identified', async () => {
        const event1 = {
            ...pluginEvent,
            properties: {
                utm_source: 'foo',
                $browser: 'Chrome',
                $current_url: 'posthog.com/page1?utm_source=foo',
            },
        }
        // posthog-js stores initial campaign params for anonymous users, and sends them if the user becomes identified
        const event2 = {
            ...pluginEvent,
            properties: {
                utm_source: 'bar',
                utm_medium: 'baz',
                $browser: 'Chrome',
                $current_url: 'posthog.com/page2?utm_source=bar&utm_medium=baz',
                $set_once: {
                    $initial_utm_source: 'foo',
                    $initial_current_url: 'posthog.com/page1?utm_source=foo',
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
                    utm_source: 'bar',
                    utm_medium: 'baz',
                    $initial_browser: 'Chrome',
                    $browser: 'Chrome',
                    $initial_current_url: 'posthog.com/page1?utm_source=foo',
                    $current_url: 'posthog.com/page2?utm_source=bar&utm_medium=baz',
                    $initial_dclid: null,
                    $initial_fbclid: null,
                    $initial_gad_source: null,
                    $initial_gbraid: null,
                    $initial_gclid: null,
                    $initial_gclsrc: null,
                    $initial_igshid: null,
                    $initial_li_fat_id: null,
                    $initial_mc_cid: null,
                    $initial_msclkid: null,
                    $initial_rdt_cid: null,
                    $initial_ttclid: null,
                    $initial_twclid: null,
                    $initial_utm_campaign: null,
                    $initial_utm_content: null,
                    $initial_utm_medium: null, // null is correct, rather than "baz"
                    $initial_utm_name: null,
                    $initial_utm_source: 'foo',
                    $initial_utm_term: null,
                    $initial_wbraid: null,
                },
                version: 0,
            })
        )

        // Check PG state
        const persons = await fetchPostgresPersons(runner.hub.db, teamId)
        expect(persons).toEqual([resPerson2])
    })

    it('ignores non-initial campaign params when upgrading user from anonymous to identified', async () => {
        const event1 = {
            ...pluginEvent,
            properties: {
                $browser: 'Chrome',
                $current_url: 'posthog.com/page1',
            },
        }
        // posthog-js stores initial campaign params for anonymous users, and sends them if the user becomes identified
        const event2 = {
            ...pluginEvent,
            properties: {
                utm_source: 'bar',
                $browser: 'Chrome',
                $current_url: 'posthog.com/page2?utm_source=bar',
                $set_once: {
                    $initial_current_url: 'posthog.com/page1',
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
                    // no $initial_utm_source
                    utm_source: 'bar',
                    $initial_browser: 'Chrome',
                    $browser: 'Chrome',
                    $initial_current_url: 'posthog.com/page1',
                    $current_url: 'posthog.com/page2?utm_source=bar',
                    $initial_dclid: null,
                    $initial_fbclid: null,
                    $initial_gad_source: null,
                    $initial_gbraid: null,
                    $initial_gclid: null,
                    $initial_gclsrc: null,
                    $initial_igshid: null,
                    $initial_li_fat_id: null,
                    $initial_mc_cid: null,
                    $initial_msclkid: null,
                    $initial_rdt_cid: null,
                    $initial_ttclid: null,
                    $initial_twclid: null,
                    $initial_utm_campaign: null,
                    $initial_utm_content: null,
                    $initial_utm_medium: null,
                    $initial_utm_name: null,
                    $initial_utm_source: null, // null is correct, rather than 'bar'
                    $initial_utm_term: null,
                    $initial_wbraid: null,
                },
                version: 0,
            })
        )

        // Check PG state
        const persons = await fetchPostgresPersons(runner.hub.db, teamId)
        expect(persons).toEqual([resPerson2])
    })
})
