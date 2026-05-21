import { mockProducer } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'

import { ASYNC_OUTPUT } from '~/ingestion/analytics/outputs'
import { PipelineResultType, isDlqResult, isOkResult, isRedirectResult } from '~/ingestion/pipelines/results'
import { PluginEvent } from '~/plugin-scaffold'
import { BatchWritingPersonsStore } from '~/worker/ingestion/persons/batch-writing-person-store'
import { PostgresPersonRepository } from '~/worker/ingestion/persons/repositories/postgres-person-repository'

import {
    createOrganization,
    createTeam,
    fetchPostgresPersons,
    getTeam,
    resetTestDatabase,
} from '../../../tests/helpers/sql'
import { KAFKA_INGESTION_WARNINGS, KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID } from '../../config/kafka-topics'
import { Hub, Person, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { normalizeEvent, normalizeProcessPerson } from '../../utils/event'
import { UUIDT } from '../../utils/utils'
import { PersonOutputs } from '../../worker/ingestion/persons/person-context'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT } from '../analytics/outputs'
import { INGESTION_WARNINGS_OUTPUT } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { SingleIngestionOutput } from '../outputs/single-ingestion-output'
import { EventPipelineRunnerOptions } from './event-pipeline-options'
import { ProcessPersonsInput, createProcessPersonsStep } from './process-persons-step'

describe('createProcessPersonsStep', () => {
    let hub: Hub
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
        PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
        PERSON_PROPERTIES_UPDATE_ALL: false,
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        const organizationId = await createOrganization(hub.postgres)
        teamId = await createTeam(hub.postgres, organizationId)
        team = (await getTeam(hub.postgres, teamId))!

        personRepository = new PostgresPersonRepository(hub.postgres)
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
        })
        const ingestionWarningsOutputs = new IngestionOutputs({
            [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                INGESTION_WARNINGS_OUTPUT,
                KAFKA_INGESTION_WARNINGS,
                mockProducer,
                'test'
            ),
        })
        personsStore = new BatchWritingPersonsStore(personRepository, ingestionWarningsOutputs)

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
        const step = createProcessPersonsStep(options, personOutputs, personsStore)
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
        const normalizedEvent = normalizeProcessPerson(normalizeEvent(event), processPerson)
        const normalizedTimestamp = parseEventTimestamp(normalizedEvent)

        const step = createProcessPersonsStep(options, personOutputs, personsStore)
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

        const step = createProcessPersonsStep(options, personOutputs, personsStore)
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

        const step = createProcessPersonsStep(options, personOutputs, personsStore)
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
        const step = createProcessPersonsStep(options, personOutputs, personsStore)
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

        const step = createProcessPersonsStep(limitOptions, personOutputs, personsStore)
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

        const personsBefore = await fetchPostgresPersons(hub.postgres, teamId)
        const initialLastSeenAt = personsBefore[0].last_seen_at

        const futureTimestamp = DateTime.utc().plus({ hours: 2 }).toISO()!
        const laterEvent: PluginEvent = {
            ...pluginEvent,
            timestamp: futureTimestamp,
            now: futureTimestamp,
            uuid: new UUIDT().toString(),
        }

        const step = createProcessPersonsStep(options, personOutputs, personsStore)
        const result = await step(
            createInput({
                normalizedEvent: laterEvent,
                timestamp: DateTime.fromISO(laterEvent.timestamp!),
            })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        await personsStore.flush()
        const persons = await fetchPostgresPersons(hub.postgres, teamId)
        expect(persons).toHaveLength(1)
        expect(persons[0].last_seen_at).toEqual(initialLastSeenAt)
    })

    it('updates last_seen_at when person_last_seen_at_enabled is true', async () => {
        const organizationId = await createOrganization(hub.postgres)
        const enabledTeamId = await createTeam(hub.postgres, organizationId, undefined, {
            extra_settings: JSON.stringify({ person_last_seen_at_enabled: true }),
        })
        const enabledTeam = (await getTeam(hub.postgres, enabledTeamId))!

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

        const step = createProcessPersonsStep(options, personOutputs, personsStore)
        const result = await step(
            createInput({
                normalizedEvent: laterEvent,
                team: enabledTeam,
                timestamp: DateTime.fromISO(laterEvent.timestamp!),
            })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        await personsStore.flush()
        const persons = await fetchPostgresPersons(hub.postgres, enabledTeamId)
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

        const step = createProcessPersonsStep(asyncOptions, personOutputs, personsStore)
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
