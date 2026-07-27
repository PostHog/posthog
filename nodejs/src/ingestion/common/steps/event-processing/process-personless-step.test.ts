import { mockProducer } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'

import { KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID, KAFKA_PERSON_MERGE_EVENTS } from '~/common/config/kafka-topics'
import { INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT, PERSON_MERGE_EVENTS_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { PostgresPersonRepository } from '~/common/persons/repositories/postgres-person-repository'
import { UUIDT } from '~/common/utils/utils'
import { BatchWritingPersonsStore } from '~/ingestion/common/persons/batch-writing-person-store'
import { BatchBoundPersonsStore } from '~/ingestion/common/persons/persons-store-for-batch'
import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { PluginEvent, Properties } from '~/plugin-scaffold'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { IngestionTestInfra, createIngestionTestInfra } from '~/tests/helpers/ingestion-e2e'
import { createOrganization, createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { EventHeaders, InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { createNormalizeEventStep } from './normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from './normalize-process-person-flag-step'
import { ProcessPersonlessInput, createProcessPersonlessStep } from './process-personless-step'

function createPersonOutputs(_infra: IngestionTestInfra) {
    return new IngestionOutputs({
        [PERSONS_OUTPUT]: new SingleIngestionOutput(PERSONS_OUTPUT, KAFKA_PERSON, mockProducer, 'test'),
        [PERSON_DISTINCT_IDS_OUTPUT]: new SingleIngestionOutput(
            PERSON_DISTINCT_IDS_OUTPUT,
            KAFKA_PERSON_DISTINCT_ID,
            mockProducer,
            'test'
        ),
    })
}

async function createPerson(
    infra: IngestionTestInfra,
    createdAt: DateTime,
    properties: Properties,
    propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
    propertiesLastOperation: PropertiesLastOperation,
    teamId: number,
    isUserId: number | null,
    isIdentified: boolean,
    uuid: string,
    primaryDistinctId: { distinctId: string; version?: number },
    extraDistinctIds?: { distinctId: string; version?: number }[]
): Promise<InternalPerson> {
    const personRepository = new PostgresPersonRepository(infra.postgres)
    const result = await personRepository.createPerson(
        createdAt,
        properties,
        propertiesLastUpdatedAt,
        propertiesLastOperation,
        teamId,
        isUserId,
        isIdentified,
        uuid,
        primaryDistinctId,
        extraDistinctIds
    )
    if (!result.success) {
        throw new Error('Failed to create person')
    }
    const personOutputs = createPersonOutputs(infra)
    await Promise.all(result.messages.map((msg) => personOutputs.produce(msg.output, { value: msg.value, key: null })))
    return result.person
}

describe('createProcessPersonlessStep', () => {
    let infra: IngestionTestInfra
    let teamId: number
    let team: Team
    let pluginEvent: PluginEvent
    let timestamp: DateTime
    let personsStore: BatchWritingPersonsStore

    beforeEach(async () => {
        await resetTestDatabase()
        infra = await createIngestionTestInfra()
        const organizationId = await createOrganization(infra.postgres)
        teamId = await createTeam(infra.postgres, organizationId)
        team = (await getTeam(infra.postgres, teamId))!

        const personRepository = new PostgresPersonRepository(infra.postgres)
        const storeOutputs = new IngestionOutputs({
            [PERSONS_OUTPUT]: new SingleIngestionOutput(PERSONS_OUTPUT, KAFKA_PERSON, mockProducer, 'test'),
            [PERSON_DISTINCT_IDS_OUTPUT]: new SingleIngestionOutput(
                PERSON_DISTINCT_IDS_OUTPUT,
                KAFKA_PERSON_DISTINCT_ID,
                mockProducer,
                'test'
            ),
            [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                INGESTION_WARNINGS_OUTPUT,
                'ingestion_warnings_test',
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
        personsStore = new BatchWritingPersonsStore(personRepository, storeOutputs)

        pluginEvent = {
            distinct_id: 'test-user-123',
            ip: null,
            site_url: 'http://localhost',
            team_id: teamId,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: '$pageview',
            properties: {},
            uuid: new UUIDT().toString(),
        }
        timestamp = DateTime.fromISO(pluginEvent.timestamp!)
    })

    afterEach(async () => {
        await infra.close()
    })

    const createInput = (overrides: Partial<ProcessPersonlessInput> = {}): ProcessPersonlessInput => ({
        normalizedEvent: pluginEvent,
        team,
        timestamp,
        processPerson: false,
        processPersonExplicitlyTrue: false,
        forceDisablePersonProcessing: false,
        personsStoreForBatch: new BatchBoundPersonsStore(personsStore, 0),
        ...overrides,
    })

    // Builds the step with the flag-called personless default enabled for all teams. The
    // production default is '' (opt-in per team), so tests opt in explicitly here.
    const buildStep = () => createProcessPersonlessStep('*')

    it('passes through when processPerson is true', async () => {
        const step = buildStep()
        const input = createInput({ processPerson: true })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.personlessPerson).toBeUndefined()
        }
    })

    describe('$feature_flag_called personless default', () => {
        const flagCalledEvent = (properties: Properties = {}): PluginEvent => ({
            ...pluginEvent,
            event: '$feature_flag_called',
            properties: { $feature_flag: 'new-homepage', $feature_flag_response: 'test', ...properties },
        })

        it('keeps the event personful when a person already exists', async () => {
            const personUuid = new UUIDT().toString()

            await createPerson(infra, timestamp, { name: 'John' }, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = buildStep()
            const result = await step(createInput({ processPerson: true, normalizedEvent: flagCalledEvent() }))

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.personlessPerson).toBeUndefined()
            }
        })

        it('keeps the event personful when it carries group keys', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')

            const step = buildStep()
            const result = await step(
                createInput({
                    processPerson: true,
                    normalizedEvent: flagCalledEvent({ $groups: { organization: 'org-1' } }),
                })
            )

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.personlessPerson).toBeUndefined()
            }
            expect(fetchForCheckingSpy).not.toHaveBeenCalled()
        })

        it('still defaults to personless when $groups is empty', async () => {
            const step = buildStep()
            const result = await step(
                createInput({ processPerson: true, normalizedEvent: flagCalledEvent({ $groups: {} }) })
            )

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.personlessPerson).toBeDefined()
            }
        })

        it('keeps the event personful when the default is disabled via config', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')

            const step = createProcessPersonlessStep('')
            const result = await step(createInput({ processPerson: true, normalizedEvent: flagCalledEvent() }))

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.personlessPerson).toBeUndefined()
            }
            expect(fetchForCheckingSpy).not.toHaveBeenCalled()
        })

        it('applies the default when the team is in the configured team list', async () => {
            const step = createProcessPersonlessStep(`${teamId}`)
            const result = await step(createInput({ processPerson: true, normalizedEvent: flagCalledEvent() }))

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.personlessPerson).toBeDefined()
            }
        })

        it('keeps the event personful when $process_person_profile was explicitly true', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')

            const step = buildStep()
            const result = await step(
                createInput({
                    processPerson: true,
                    processPersonExplicitlyTrue: true,
                    normalizedEvent: flagCalledEvent(),
                })
            )

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.personlessPerson).toBeUndefined()
            }
            expect(fetchForCheckingSpy).not.toHaveBeenCalled()
        })

        it('defaults to personless and records the distinct ID when no person exists', async () => {
            const addPersonlessDistinctIdSpy = jest.spyOn(personsStore, 'addPersonlessDistinctId')

            const step = buildStep()
            const result = await step(
                createInput({
                    processPerson: true,
                    normalizedEvent: flagCalledEvent({ $set: { email: 'user@example.com' } }),
                })
            )

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.personlessPerson).toBeDefined()
                expect(result.value.personlessPerson!.properties).toEqual({})
                // The event is re-normalized as personless: $set stripped, personless stamp added.
                expect(result.value.normalizedEvent.properties?.$set).toBeUndefined()
                expect(result.value.normalizedEvent.properties?.$process_person_profile).toBe(false)
            }
            expect(addPersonlessDistinctIdSpy).toHaveBeenCalledWith(teamId, pluginEvent.distinct_id, 0)
        })

        it('skips the personless distinct ID insert when the batch already has a result', async () => {
            jest.spyOn(personsStore, 'getPersonlessBatchResult').mockReturnValue(false)
            const addPersonlessDistinctIdSpy = jest.spyOn(personsStore, 'addPersonlessDistinctId')

            const step = buildStep()
            const result = await step(createInput({ processPerson: true, normalizedEvent: flagCalledEvent() }))

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(false)
            }
            expect(addPersonlessDistinctIdSpy).not.toHaveBeenCalled()
        })

        it('keeps the event personful when the distinct ID turns out to be merged', async () => {
            const personUuid = new UUIDT().toString()
            const person = await createPerson(infra, timestamp, {}, {}, {}, teamId, null, false, personUuid, {
                distinctId: 'merge-target',
            })

            jest.spyOn(personsStore, 'fetchForChecking').mockResolvedValue(null)
            jest.spyOn(personsStore, 'addPersonlessDistinctId').mockResolvedValue(true)
            const fetchForUpdateSpy = jest.spyOn(personsStore, 'fetchForUpdate').mockResolvedValue(person)

            const step = buildStep()
            const result = await step(createInput({ processPerson: true, normalizedEvent: flagCalledEvent() }))

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.personlessPerson).toBeUndefined()
            }
            expect(fetchForUpdateSpy).toHaveBeenCalledWith(teamId, pluginEvent.distinct_id, 0)
        })

        it('defaults to personless when the merged person cannot be fetched from the leader', async () => {
            jest.spyOn(personsStore, 'fetchForChecking').mockResolvedValue(null)
            jest.spyOn(personsStore, 'addPersonlessDistinctId').mockResolvedValue(true)
            jest.spyOn(personsStore, 'fetchForUpdate').mockResolvedValue(null)

            const step = buildStep()
            const result = await step(createInput({ processPerson: true, normalizedEvent: flagCalledEvent() }))

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.personlessPerson).toBeDefined()
            }
        })

        it('takes the generic personless path, not the defaulting branch, when already force-disabled', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')
            const addPersonlessDistinctIdSpy = jest.spyOn(personsStore, 'addPersonlessDistinctId')

            const step = buildStep()
            const result = await step(
                createInput({ normalizedEvent: flagCalledEvent(), forceDisablePersonProcessing: true })
            )

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.personlessPerson).toBeDefined()
            }
            expect(fetchForCheckingSpy).not.toHaveBeenCalled()
            expect(addPersonlessDistinctIdSpy).not.toHaveBeenCalled()
        })

        // Pipes an event through the same normalization steps that precede the personless
        // step in the real subpipeline, so these tests cover the boundary where
        // normalizeProcessPerson strips the explicit $process_person_profile property.
        const runThroughNormalization = async (event: PluginEvent): Promise<ProcessPersonlessInput> => {
            const normalizeFlagStep = createNormalizeProcessPersonFlagStep<{
                event: PluginEvent
                headers: EventHeaders
                team: Team
            }>()
            const flagResult = await normalizeFlagStep({ event, team, headers: createTestEventHeaders() })
            if (!isOkResult(flagResult)) {
                throw new Error('expected normalize flag step to return ok')
            }

            const normalizeEventStep = createNormalizeEventStep<typeof flagResult.value>()
            const normalizeResult = await normalizeEventStep(flagResult.value)
            if (!isOkResult(normalizeResult)) {
                throw new Error('expected normalize event step to return ok')
            }
            return { ...normalizeResult.value, personsStoreForBatch: new BatchBoundPersonsStore(personsStore, 0) }
        }

        it('keeps an explicit-true event personful after normalization strips the property', async () => {
            const personlessStep = buildStep()
            const normalized = await runThroughNormalization(flagCalledEvent({ $process_person_profile: true }))

            // Normalization removes the explicit-true property for personful events, so the
            // personless step must rely on the captured processPersonExplicitlyTrue flag.
            expect(normalized.normalizedEvent.properties?.$process_person_profile).toBeUndefined()

            const result = await personlessStep(normalized)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.personlessPerson).toBeUndefined()
            }
        })

        it('defaults an event without the property to personless through normalization', async () => {
            const personlessStep = buildStep()
            const normalized = await runThroughNormalization(flagCalledEvent())

            const result = await personlessStep(normalized)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.personlessPerson).toBeDefined()
                expect(result.value.normalizedEvent.properties?.$process_person_profile).toBe(false)
            }
        })

        it('skips the defaulting branch for explicit $process_person_profile=false events', async () => {
            const addPersonlessDistinctIdSpy = jest.spyOn(personsStore, 'addPersonlessDistinctId')

            const personlessStep = buildStep()
            const normalized = await runThroughNormalization(flagCalledEvent({ $process_person_profile: false }))

            const result = await personlessStep(normalized)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.personlessPerson).toBeDefined()
            }
            // The plain personless path leaves the insert to the batch step.
            expect(addPersonlessDistinctIdSpy).not.toHaveBeenCalled()
        })
    })

    describe('basic personless functionality', () => {
        it('returns fake person when no existing person found', async () => {
            const step = buildStep()
            const result = await step(createInput())

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value.personlessPerson!
                expect(person.team_id).toBe(teamId)
                expect(person.properties).toEqual({})
                expect(person.uuid).toBeDefined()
                expect(person.created_at.toISO()).toBe('1970-01-01T00:00:05.000Z')
                expect(person.force_upgrade).toBeUndefined()
            }
        })

        it('returns existing person with empty properties when person exists', async () => {
            const personUuid = new UUIDT().toString()

            await createPerson(infra, timestamp, { name: 'John' }, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = buildStep()
            const result = await step(createInput())

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value.personlessPerson!
                expect(person.uuid).toBe(personUuid)
                expect(person.properties).toEqual({})
                expect(person.force_upgrade).toBeUndefined()
            }
        })

        it('checks batch result for personless distinct ID when no person exists', async () => {
            const getPersonlessBatchResultSpy = jest.spyOn(personsStore, 'getPersonlessBatchResult')

            const step = buildStep()
            await step(createInput())

            expect(getPersonlessBatchResultSpy).toHaveBeenCalledWith(teamId, pluginEvent.distinct_id)
        })

        it('returns fake person when batch result indicates no merge', async () => {
            jest.spyOn(personsStore, 'getPersonlessBatchResult').mockReturnValue(false)

            const step = buildStep()
            const result = await step(createInput())

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value.personlessPerson!
                expect(person.created_at.toISO()).toBe('1970-01-01T00:00:05.000Z')
            }
        })
    })

    describe('force_upgrade logic', () => {
        it('sets force_upgrade=true when event timestamp > person.created_at + 1 minute', async () => {
            const personUuid = new UUIDT().toString()
            const personCreatedAt = DateTime.fromISO('2020-02-23T02:00:00Z')

            await createPerson(infra, personCreatedAt, {}, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = buildStep()
            const result = await step(createInput())

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value.personlessPerson!
                expect(person.uuid).toBe(personUuid)
                expect(person.force_upgrade).toBe(true)
            }
        })

        it('does NOT set force_upgrade when within 1-minute grace period', async () => {
            const personUuid = new UUIDT().toString()
            const personCreatedAt = DateTime.fromISO('2020-02-23T02:14:30Z')

            await createPerson(infra, personCreatedAt, {}, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = buildStep()
            const result = await step(createInput())

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value.personlessPerson!
                expect(person.uuid).toBe(personUuid)
                expect(person.force_upgrade).toBeUndefined()
            }
        })

        it('ignores force_upgrade when team.person_processing_opt_out=true', async () => {
            team.person_processing_opt_out = true

            const personUuid = new UUIDT().toString()
            const personCreatedAt = DateTime.fromISO('2020-02-23T02:00:00Z')

            await createPerson(infra, personCreatedAt, {}, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = buildStep()
            const result = await step(createInput())

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value.personlessPerson!
                expect(person.uuid).toBe(personUuid)
                expect(person.force_upgrade).toBeUndefined()
            }
        })
    })

    describe('merge detection', () => {
        it('detects when person was merged and re-fetches from leader', async () => {
            const personUuid = new UUIDT().toString()
            const personCreatedAt = DateTime.fromISO('2020-02-20T00:00:00Z')

            const person = await createPerson(
                infra,
                personCreatedAt,
                { name: 'John' },
                {},
                {},
                teamId,
                null,
                false,
                personUuid,
                { distinctId: pluginEvent.distinct_id }
            )

            jest.spyOn(personsStore, 'fetchForChecking').mockResolvedValueOnce(null)
            jest.spyOn(personsStore, 'getPersonlessBatchResult').mockReturnValue(true)
            const fetchForUpdateSpy = jest.spyOn(personsStore, 'fetchForUpdate').mockResolvedValue(person)

            const step = buildStep()
            const result = await step(createInput())

            expect(result.type).toBe(PipelineResultType.OK)
            expect(fetchForUpdateSpy).toHaveBeenCalledWith(teamId, pluginEvent.distinct_id, 0)
        })
    })

    describe('forceDisablePersonProcessing', () => {
        it('skips all DB operations and returns fake person immediately when true', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')
            const getPersonlessBatchResultSpy = jest.spyOn(personsStore, 'getPersonlessBatchResult')

            const step = buildStep()
            const result = await step(createInput({ forceDisablePersonProcessing: true }))

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value.personlessPerson!
                expect(person.team_id).toBe(teamId)
                expect(person.properties).toEqual({})
                expect(person.created_at.toISO()).toBe('1970-01-01T00:00:05.000Z')
            }

            expect(fetchForCheckingSpy).not.toHaveBeenCalled()
            expect(getPersonlessBatchResultSpy).not.toHaveBeenCalled()
        })

        it('performs normal processing when false', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')

            const step = buildStep()
            await step(createInput())

            expect(fetchForCheckingSpy).toHaveBeenCalled()
        })

        it('works with different distinct IDs', async () => {
            const distinctIds = ['user-1', 'user-2', 'user-3']
            const step = buildStep()

            for (const distinctId of distinctIds) {
                const result = await step(
                    createInput({
                        normalizedEvent: { ...pluginEvent, distinct_id: distinctId },
                        forceDisablePersonProcessing: true,
                    })
                )

                expect(result.type).toBe(PipelineResultType.OK)
                if (isOkResult(result)) {
                    expect(result.value.personlessPerson!.team_id).toBe(teamId)
                    expect(result.value.personlessPerson!.properties).toEqual({})
                }
            }
        })
    })
})
