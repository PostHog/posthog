import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineResultType, isOkResult } from '~/ingestion/pipelines/results'
import { BatchWritingPersonsStore } from '~/worker/ingestion/persons/batch-writing-person-store'

import { Hub, Team } from '../../../../src/types'
import { closeHub, createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { normalizeEventStep } from '../../../../src/worker/ingestion/event-pipeline/normalizeEventStep'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { createDefaultSyncMergeMode } from '../../../../src/worker/ingestion/persons/person-merge-types'
import { PostgresPersonRepository } from '../../../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { createOrganization, createTeam, fetchPostgresPersons, getTeam, resetTestDatabase } from '../../../helpers/sql'

describe('processPersonsStep()', () => {
    let hub: Hub

    let uuid: string
    let teamId: number
    let team: Team
    let pluginEvent: PluginEvent
    let timestamp: DateTime

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        const organizationId = await createOrganization(hub.postgres)
        teamId = await createTeam(hub.postgres, organizationId)
        team = (await getTeam(hub, teamId))!
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
        const personsStore = new BatchWritingPersonsStore(new PostgresPersonRepository(hub.postgres), hub.kafkaProducer)
        const result = await processPersonsStep(
            hub.kafkaProducer,
            createDefaultSyncMergeMode(),
            hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
            hub.PERSON_PROPERTIES_UPDATE_ALL,
            pluginEvent,
            team,
            timestamp,
            processPerson,
            personsStore
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
            const persons = await fetchPostgresPersons(hub.postgres, teamId)
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
        const [normalizedEvent, normalizedTimestamp] = await normalizeEventStep(event, processPerson)
        const personsStore = new BatchWritingPersonsStore(new PostgresPersonRepository(hub.postgres), hub.kafkaProducer)
        const result = await processPersonsStep(
            hub.kafkaProducer,
            createDefaultSyncMergeMode(),
            hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
            hub.PERSON_PROPERTIES_UPDATE_ALL,
            normalizedEvent,
            team,
            normalizedTimestamp,
            processPerson,
            personsStore
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
            const persons = await fetchPostgresPersons(hub.postgres, teamId)
            expect(persons).toEqual([resPerson])
        }
    })
})
