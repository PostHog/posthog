import { DateTime } from 'luxon'

import { PipelineResultType, isOkResult } from '~/ingestion/pipelines/results'
import { PluginEvent, Properties } from '~/plugin-scaffold'
import { BatchWritingPersonsStore } from '~/worker/ingestion/persons/batch-writing-person-store'
import { PostgresPersonRepository } from '~/worker/ingestion/persons/repositories/postgres-person-repository'

import { createOrganization, createTeam, getTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID } from '../../config/kafka-topics'
import { Hub, InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { UUIDT } from '../../utils/utils'
import { PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT } from '../analytics/outputs'
import { INGESTION_WARNINGS_OUTPUT } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { SingleIngestionOutput } from '../outputs/single-ingestion-output'
import { ProcessPersonlessInput, createProcessPersonlessStep } from './process-personless-step'

function createPersonOutputs(hub: Hub) {
    return new IngestionOutputs({
        [PERSONS_OUTPUT]: new SingleIngestionOutput(PERSONS_OUTPUT, KAFKA_PERSON, hub.kafkaProducer, 'test'),
        [PERSON_DISTINCT_IDS_OUTPUT]: new SingleIngestionOutput(
            PERSON_DISTINCT_IDS_OUTPUT,
            KAFKA_PERSON_DISTINCT_ID,
            hub.kafkaProducer,
            'test'
        ),
    })
}

async function createPerson(
    hub: Hub,
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
    const personRepository = new PostgresPersonRepository(hub.postgres)
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
    const personOutputs = createPersonOutputs(hub)
    await Promise.all(result.messages.map((msg) => personOutputs.produce(msg.output, { value: msg.value, key: null })))
    return result.person
}

describe('createProcessPersonlessStep', () => {
    let hub: Hub
    let teamId: number
    let team: Team
    let pluginEvent: PluginEvent
    let timestamp: DateTime
    let personsStore: BatchWritingPersonsStore

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        const organizationId = await createOrganization(hub.postgres)
        teamId = await createTeam(hub.postgres, organizationId)
        team = (await getTeam(hub.postgres, teamId))!

        const personRepository = new PostgresPersonRepository(hub.postgres)
        const ingestionWarningsOutputs = new IngestionOutputs({
            [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                INGESTION_WARNINGS_OUTPUT,
                'ingestion_warnings_test',
                hub.kafkaProducer,
                'test'
            ),
        })
        personsStore = new BatchWritingPersonsStore(personRepository, ingestionWarningsOutputs)

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
        await closeHub(hub)
    })

    const createInput = (overrides: Partial<ProcessPersonlessInput> = {}): ProcessPersonlessInput => ({
        normalizedEvent: pluginEvent,
        team,
        timestamp,
        processPerson: false,
        forceDisablePersonProcessing: false,
        ...overrides,
    })

    it('passes through when processPerson is true', async () => {
        const step = createProcessPersonlessStep(personsStore)
        const input = createInput({ processPerson: true })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.personlessPerson).toBeUndefined()
        }
    })

    describe('basic personless functionality', () => {
        it('returns fake person when no existing person found', async () => {
            const step = createProcessPersonlessStep(personsStore)
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

            await createPerson(hub, timestamp, { name: 'John' }, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = createProcessPersonlessStep(personsStore)
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

            const step = createProcessPersonlessStep(personsStore)
            await step(createInput())

            expect(getPersonlessBatchResultSpy).toHaveBeenCalledWith(teamId, pluginEvent.distinct_id)
        })

        it('returns fake person when batch result indicates no merge', async () => {
            jest.spyOn(personsStore, 'getPersonlessBatchResult').mockReturnValue(false)

            const step = createProcessPersonlessStep(personsStore)
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

            await createPerson(hub, personCreatedAt, {}, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = createProcessPersonlessStep(personsStore)
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

            await createPerson(hub, personCreatedAt, {}, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = createProcessPersonlessStep(personsStore)
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

            await createPerson(hub, personCreatedAt, {}, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const step = createProcessPersonlessStep(personsStore)
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
                hub,
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

            const step = createProcessPersonlessStep(personsStore)
            const result = await step(createInput())

            expect(result.type).toBe(PipelineResultType.OK)
            expect(fetchForUpdateSpy).toHaveBeenCalledWith(teamId, pluginEvent.distinct_id)
        })
    })

    describe('forceDisablePersonProcessing', () => {
        it('skips all DB operations and returns fake person immediately when true', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')
            const getPersonlessBatchResultSpy = jest.spyOn(personsStore, 'getPersonlessBatchResult')

            const step = createProcessPersonlessStep(personsStore)
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

            const step = createProcessPersonlessStep(personsStore)
            await step(createInput())

            expect(fetchForCheckingSpy).toHaveBeenCalled()
        })

        it('works with different distinct IDs', async () => {
            const distinctIds = ['user-1', 'user-2', 'user-3']
            const step = createProcessPersonlessStep(personsStore)

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
