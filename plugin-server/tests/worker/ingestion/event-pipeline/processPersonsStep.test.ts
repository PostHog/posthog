import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineResultType, isOkResult } from '~/ingestion/pipelines/results'
import { BatchWritingPersonsStoreForBatch } from '~/worker/ingestion/persons/batch-writing-person-store'

import { Hub, Team } from '../../../../src/types'
import { closeHub, createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { normalizeEventStep } from '../../../../src/worker/ingestion/event-pipeline/normalizeEventStep'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { PostgresPersonRepository } from '../../../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { EventsProcessor } from '../../../../src/worker/ingestion/process-event'
import { createOrganization, createTeam, fetchPostgresPersons, getTeam, resetTestDatabase } from '../../../helpers/sql'

describe('processPersonsStep()', () => {
    let runner: Pick<EventPipelineRunner, 'hub' | 'eventsProcessor'>
    let hub: Hub

    let uuid: string
    let teamId: number
    let team: Team
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
        team = (await getTeam(runner.hub, teamId))!
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
        const result = await processPersonsStep(
            runner as EventPipelineRunner,
            pluginEvent,
            team,
            timestamp,
            processPerson,
            new BatchWritingPersonsStoreForBatch(
                new PostgresPersonRepository(runner.hub.db.postgres),
                runner.hub.kafkaProducer
            )
        )

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            const [resEvent, resPerson, kafkaAck] = result.value
            expect(resEvent).toEqual(pluginEvent)
            expect(resPerson).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: expect.any(String),
                    properties: { a: 5, $creator_event_uuid: expect.any(String) },
                    version: 0,
                    is_identified: false,
                    team_id: teamId,
                })
            )

            // Wait for kafka ack
            await kafkaAck

            // Check PG state
            const persons = await fetchPostgresPersons(runner.hub.db, teamId)
            expect(persons).toEqual([resPerson])
        }
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
        const result = await processPersonsStep(
            runner as EventPipelineRunner,
            normalizedEvent,
            team,
            timestamp,
            processPerson,
            new BatchWritingPersonsStoreForBatch(
                new PostgresPersonRepository(runner.hub.db.postgres),
                runner.hub.kafkaProducer
            )
        )

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            const [resEvent, resPerson, kafkaAck] = result.value
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
                    id: expect.any(String),
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

            // Wait for kafka ack
            await kafkaAck

            // Check PG state
            const persons = await fetchPostgresPersons(runner.hub.db, teamId)
            expect(persons).toEqual([resPerson])
        }
    })
})
