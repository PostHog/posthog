import { mockProducer } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'

import {
    KAFKA_INGESTION_WARNINGS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_MERGE_EVENTS,
} from '~/common/config/kafka-topics'
import { INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { ASYNC_OUTPUT } from '~/common/outputs'
import { PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT, PERSON_MERGE_EVENTS_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { PostgresPersonRepository } from '~/common/persons/repositories/postgres-person-repository'
import { normalizeEvent, normalizeProcessPerson } from '~/common/utils/event'
import { UUIDT } from '~/common/utils/utils'
import { BatchWritingPersonsStore } from '~/ingestion/common/persons/batch-writing-person-store'
import { PersonOutputs } from '~/ingestion/common/persons/person-context'
import { BatchBoundPersonsStore } from '~/ingestion/common/persons/persons-store-for-batch'
import { EventPipelineRunnerOptions } from '~/ingestion/common/steps/event-processing/event-pipeline-options'
import {
    ProcessPersonsInput,
    createProcessPersonsStep,
} from '~/ingestion/common/steps/event-processing/process-persons-step'
import { parseEventTimestamp } from '~/ingestion/common/timestamps'
import { PipelineResultType, isDlqResult, isOkResult, isRedirectResult } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { IngestionTestInfra, createIngestionTestInfra } from '~/tests/helpers/ingestion-e2e'
import { createOrganization, createTeam, fetchPostgresPersons, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Person, Team } from '~/types'

describe('createProcessPersonsStep', () => {
    let infra: IngestionTestInfra
    let teamId: number
    let team: Team
    let pluginEvent: PluginEvent
    let timestamp: DateTime
    let personRepository: PostgresPersonRepository
    let personsStore: BatchWritingPersonsStore
    let personOutputs: PersonOutputs

    const options: EventPipelineRunnerOptions = {
        SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 100,
        PERSON_MERGE_ASYNC_ENABLED: false,
        PERSON_MERGE_SYNC_BATCH_SIZE: 1,
        PERSON_MERGE_EVENTS_ENABLED: false,
        PERSON_MERGE_EVENTS_PARTITION_COUNT: 64,
        PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
        PERSON_PROPERTIES_UPDATE_ALL: false,
        FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS: '*',
    }

    beforeEach(async () => {
        await resetTestDatabase()
        infra = await createIngestionTestInfra()
        const organizationId = await createOrganization(infra.postgres)
        teamId = await createTeam(infra.postgres, organizationId)
        team = (await getTeam(infra.postgres, teamId))!

        personRepository = new PostgresPersonRepository(infra.postgres)
        personOutputs = new IngestionOutputs({
            [PERSONS_OUTPUT]: new SingleIngestionOutput(PERSONS_OUTPUT, KAFKA_PERSON, mockProducer, 'test'),
            [PERSON_DISTINCT_IDS_OUTPUT]: new SingleIngestionOutput(
                INGESTION_WARNINGS_OUTPUT,
                KAFKA_PERSON_DISTINCT_ID,
                mockProducer,
                'test'
            ),
            [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                INGESTION_WARNINGS_OUTPUT,
                KAFKA_INGESTION_WARNINGS,
                mockProducer,
                'test'
            ),
            [PERSON_MERGE_EVENTS_OUTPUT]: new SingleIngestionOutput(
                PERSON_MERGE_EVENTS_OUTPUT,
                KAFKA_PERSON_MERGE_EVENTS,
                mockProducer,
                'test'
            ),
        })
        personsStore = new BatchWritingPersonsStore(personRepository, personOutputs)

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
        await infra.close()
    })

    const createInput = (overrides: Partial<ProcessPersonsInput> = {}): ProcessPersonsInput => ({
        normalizedEvent: pluginEvent,
        team,
        timestamp,
        personsStoreForBatch: new BatchBoundPersonsStore(personsStore, 0),
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
        const step = createProcessPersonsStep(options, personOutputs)
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
            const persons = await fetchPostgresPersons(infra.postgres, teamId)
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
        const normalizedEvent = normalizeProcessPerson(normalizeEvent(event), processPerson)
        const normalizedTimestamp = parseEventTimestamp(normalizedEvent)

        const step = createProcessPersonsStep(options, personOutputs)
        const result = await step(createInput({ normalizedEvent, timestamp: normalizedTimestamp }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.normalizedEvent).toEqual({
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
            const persons = await fetchPostgresPersons(infra.postgres, teamId)
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

        const step = createProcessPersonsStep(options, personOutputs)
        const result = await step(createInput({ personlessPerson }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.person).toBe(personlessPerson)
            expect(result.sideEffects).toEqual([])
        }

        const persons = await fetchPostgresPersons(infra.postgres, teamId)
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

        const step = createProcessPersonsStep(options, personOutputs)
        const result = await step(createInput({ personlessPerson }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.person.force_upgrade).toBe(true)
            expect(result.sideEffects.length).toBeGreaterThan(0)
        }

        await personsStore.flush()
        const persons = await fetchPostgresPersons(infra.postgres, teamId)
        expect(persons.length).toBe(1)
    })

    it('preserves additional input fields in the output', async () => {
        const step = createProcessPersonsStep(options, personOutputs)
        const input = { ...createInput(), extraField: 'preserved' }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect((result.value as any).extraField).toBe('preserved')
            expect(result.value.team).toBe(input.team)
            expect(result.value.timestamp).toBe(input.timestamp)
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

        const step = createProcessPersonsStep(limitOptions, personOutputs)
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

    it('does not update last_seen_at when person_last_seen_at_enabled is not set', async () => {
        await createPersonWithDistinctIds('my_id')

        const personsBefore = await fetchPostgresPersons(infra.postgres, teamId)
        const initialLastSeenAt = personsBefore[0].last_seen_at

        const futureTimestamp = DateTime.utc().plus({ hours: 2 }).toISO()!
        const laterEvent: PluginEvent = {
            ...pluginEvent,
            timestamp: futureTimestamp,
            now: futureTimestamp,
            uuid: new UUIDT().toString(),
        }

        const step = createProcessPersonsStep(options, personOutputs)
        const result = await step(
            createInput({
                normalizedEvent: laterEvent,
                timestamp: DateTime.fromISO(laterEvent.timestamp!),
            })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        await personsStore.flush()
        const persons = await fetchPostgresPersons(infra.postgres, teamId)
        expect(persons).toHaveLength(1)
        expect(persons[0].last_seen_at).toEqual(initialLastSeenAt)
    })

    it('updates last_seen_at when person_last_seen_at_enabled is true', async () => {
        const organizationId = await createOrganization(infra.postgres)
        const enabledTeamId = await createTeam(infra.postgres, organizationId, undefined, {
            extra_settings: JSON.stringify({ person_last_seen_at_enabled: true }),
        })
        const enabledTeam = (await getTeam(infra.postgres, enabledTeamId))!

        await personRepository.createPerson(
            DateTime.utc(),
            {},
            {},
            {},
            enabledTeamId,
            null,
            false,
            new UUIDT().toString(),
            { distinctId: 'my_id' }
        )

        const futureTimestamp = DateTime.utc().plus({ hours: 2 })
        const laterEvent: PluginEvent = {
            ...pluginEvent,
            team_id: enabledTeamId,
            timestamp: futureTimestamp.toISO()!,
            now: futureTimestamp.toISO()!,
            uuid: new UUIDT().toString(),
        }

        const step = createProcessPersonsStep(options, personOutputs)
        const result = await step(
            createInput({
                normalizedEvent: laterEvent,
                team: enabledTeam,
                timestamp: DateTime.fromISO(laterEvent.timestamp!),
            })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        await personsStore.flush()
        const persons = await fetchPostgresPersons(infra.postgres, enabledTeamId)
        expect(persons).toHaveLength(1)
        expect(persons[0].last_seen_at).toEqual(futureTimestamp.startOf('hour'))
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
        }

        const step = createProcessPersonsStep(asyncOptions, personOutputs)
        const result = await step(
            createInput({
                normalizedEvent: identifyEvent,
                timestamp: DateTime.fromISO(identifyEvent.timestamp!),
            })
        )

        expect(result.type).toBe(PipelineResultType.REDIRECT)
        if (isRedirectResult(result)) {
            expect(result.reason).toBe('Event redirected to async merge topic')
            expect(result.output).toBe(ASYNC_OUTPUT)
        }
    })
})
