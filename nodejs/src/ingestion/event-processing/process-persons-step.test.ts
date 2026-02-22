import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineResultType, isDlqResult, isOkResult, isRedirectResult } from '~/ingestion/pipelines/results'
import { BatchWritingPersonsStore } from '~/worker/ingestion/persons/batch-writing-person-store'
import { PostgresPersonRepository } from '~/worker/ingestion/persons/repositories/postgres-person-repository'

import {
    createOrganization,
    createTeam,
    fetchPostgresPersons,
    getTeam,
    resetTestDatabase,
} from '../../../tests/helpers/sql'
import { Hub, Person, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { UUIDT } from '../../utils/utils'
import { normalizeEventStep } from '../../worker/ingestion/event-pipeline/normalizeEventStep'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { ProcessPersonsInput, createProcessPersonsStep } from './process-persons-step'

describe('createProcessPersonsStep', () => {
    let hub: Hub
    let teamId: number
    let team: Team
    let pluginEvent: PluginEvent
    let timestamp: DateTime
    let personRepository: PostgresPersonRepository
    let personsStore: BatchWritingPersonsStore

    const options: EventPipelineRunnerOptions = {
        SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: 0,
        PIPELINE_STEP_STALLED_LOG_TIMEOUT: 30000,
        PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 100,
        PERSON_MERGE_ASYNC_ENABLED: false,
        PERSON_MERGE_ASYNC_TOPIC: '',
        PERSON_MERGE_SYNC_BATCH_SIZE: 1,
        PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
        PERSON_PROPERTIES_UPDATE_ALL: false,
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        const organizationId = await createOrganization(hub.postgres)
        teamId = await createTeam(hub.postgres, organizationId)
        team = (await getTeam(hub, teamId))!

        personRepository = new PostgresPersonRepository(hub.postgres)
        personsStore = new BatchWritingPersonsStore(personRepository, hub.kafkaProducer)

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
            uuid: new UUIDT().toString(),
        }
        timestamp = DateTime.fromISO(pluginEvent.timestamp!)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const createInput = (overrides: Partial<ProcessPersonsInput> = {}): ProcessPersonsInput => ({
        normalizedEvent: pluginEvent,
        team,
        timestamp,
        ...overrides,
    })

    async function createPersonWithDistinctIds(distinctId: string, ...extraDistinctIds: string[]) {
        const result = await personRepository.createPerson(
            DateTime.utc(),
            {},
            {},
            {},
            teamId,
            null,
            false,
            new UUIDT().toString(),
            { distinctId }
        )
        if (!result.success) {
            throw new Error(`Failed to create person with distinct_id ${distinctId}`)
        }
        for (const extraId of extraDistinctIds) {
            await personRepository.addDistinctId(result.person, extraId, 1)
        }
        return result.person
    }

    it('creates person with $set properties', async () => {
        const step = createProcessPersonsStep(options, hub.kafkaProducer, personsStore)
        const result = await step(createInput())

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: expect.any(String),
                    properties: { a: 5, $creator_event_uuid: expect.any(String) },
                    version: 0,
                    is_identified: false,
                    team_id: teamId,
                })
            )

            await personsStore.flush()
            const persons = await fetchPostgresPersons(hub.postgres, teamId)
            expect(persons).toEqual([result.value.person])
        }
    })

    it('creates person with normalized properties from event $set', async () => {
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

        const step = createProcessPersonsStep(options, hub.kafkaProducer, personsStore)
        const result = await step(createInput({ normalizedEvent, timestamp: normalizedTimestamp }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.eventWithPerson).toEqual({
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
            expect(result.value.person).toEqual(
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

            await personsStore.flush()
            const persons = await fetchPostgresPersons(hub.postgres, teamId)
            expect(persons).toEqual([result.value.person])
        }
    })

    it('skips person processing when personlessPerson provided without force_upgrade', async () => {
        const personlessPerson: Person = {
            team_id: teamId,
            properties: {},
            uuid: new UUIDT().toString(),
            created_at: DateTime.fromISO('1970-01-01T00:00:05.000Z'),
        }

        const step = createProcessPersonsStep(options, hub.kafkaProducer, personsStore)
        const result = await step(createInput({ personlessPerson }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.person).toBe(personlessPerson)
            expect(result.sideEffects).toEqual([])
        }

        const persons = await fetchPostgresPersons(hub.postgres, teamId)
        expect(persons).toEqual([])
    })

    it('processes person when personlessPerson has force_upgrade', async () => {
        const personlessPerson: Person = {
            team_id: teamId,
            properties: {},
            uuid: new UUIDT().toString(),
            created_at: DateTime.fromISO('1970-01-01T00:00:05.000Z'),
            force_upgrade: true,
        }

        const step = createProcessPersonsStep(options, hub.kafkaProducer, personsStore)
        const result = await step(createInput({ personlessPerson }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.person.force_upgrade).toBe(true)
            expect(result.sideEffects.length).toBeGreaterThan(0)
        }

        await personsStore.flush()
        const persons = await fetchPostgresPersons(hub.postgres, teamId)
        expect(persons.length).toBe(1)
    })

    it('preserves additional input fields in the output', async () => {
        const step = createProcessPersonsStep(options, hub.kafkaProducer, personsStore)
        const input = { ...createInput(), extraField: 'preserved' }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect((result.value as any).extraField).toBe('preserved')
            expect(result.value.team).toBe(input.team)
            expect(result.value.timestamp).toBe(input.timestamp)
        }
    })

    it('replaces normalizedEvent with eventWithPerson in output', async () => {
        const step = createProcessPersonsStep(options, hub.kafkaProducer, personsStore)
        const result = await step(createInput())

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.eventWithPerson).toBeDefined()
            expect((result.value as any).normalizedEvent).toBeUndefined()
        }
    })

    it('returns DLQ result when merge limit is exceeded in LIMIT mode', async () => {
        await createPersonWithDistinctIds('person-1')
        await createPersonWithDistinctIds('person-2', 'person-2-extra-1', 'person-2-extra-2')

        const identifyEvent: PluginEvent = {
            ...pluginEvent,
            event: '$identify',
            distinct_id: 'person-1',
            properties: {
                $anon_distinct_id: 'person-2',
            },
        }

        const limitOptions: EventPipelineRunnerOptions = {
            ...options,
            PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 2,
        }

        const step = createProcessPersonsStep(limitOptions, hub.kafkaProducer, personsStore)
        const result = await step(
            createInput({
                normalizedEvent: identifyEvent,
                timestamp: DateTime.fromISO(identifyEvent.timestamp!),
            })
        )

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (isDlqResult(result)) {
            expect(result.reason).toBe('Merge limit exceeded')
        }
    })

    it('returns redirect result when merge limit is exceeded in ASYNC mode', async () => {
        await createPersonWithDistinctIds('person-1')
        await createPersonWithDistinctIds('person-2', 'person-2-extra-1', 'person-2-extra-2')

        const identifyEvent: PluginEvent = {
            ...pluginEvent,
            event: '$identify',
            distinct_id: 'person-1',
            properties: {
                $anon_distinct_id: 'person-2',
            },
        }

        const asyncOptions: EventPipelineRunnerOptions = {
            ...options,
            PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 2,
            PERSON_MERGE_ASYNC_ENABLED: true,
            PERSON_MERGE_ASYNC_TOPIC: 'async-merge-topic',
        }

        const step = createProcessPersonsStep(asyncOptions, hub.kafkaProducer, personsStore)
        const result = await step(
            createInput({
                normalizedEvent: identifyEvent,
                timestamp: DateTime.fromISO(identifyEvent.timestamp!),
            })
        )

        expect(result.type).toBe(PipelineResultType.REDIRECT)
        if (isRedirectResult(result)) {
            expect(result.reason).toBe('Event redirected to async merge topic')
            expect(result.topic).toBe('async-merge-topic')
        }
    })
})
