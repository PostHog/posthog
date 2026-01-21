import { DateTime } from 'luxon'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { PipelineResultType, isOkResult } from '~/ingestion/pipelines/results'
import { BatchWritingPersonsStore } from '~/worker/ingestion/persons/batch-writing-person-store'

import { Hub, InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../../src/types'
import { closeHub, createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { processPersonlessStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonlessStep'
import { PostgresPersonRepository } from '../../../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { createOrganization, createTeam, getTeam, resetTestDatabase } from '../../../helpers/sql'

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
    await hub.kafkaProducer.queueMessages(result.messages)
    return result.person
}

describe('processPersonlessStep()', () => {
    let hub: Hub
    let teamId: number
    let team: Team
    let pluginEvent: PluginEvent
    let timestamp: DateTime
    let personsStore: BatchWritingPersonsStore
    let personRepository: PostgresPersonRepository

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        const organizationId = await createOrganization(hub.postgres)
        teamId = await createTeam(hub.postgres, organizationId)
        team = (await getTeam(hub, teamId))!

        personRepository = new PostgresPersonRepository(hub.postgres)
        personsStore = new BatchWritingPersonsStore(personRepository, hub.kafkaProducer)

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

    describe('basic personless functionality', () => {
        it('returns fake person when no existing person found', async () => {
            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value
                expect(person.team_id).toBe(teamId)
                expect(person.properties).toEqual({})
                expect(person.uuid).toBeDefined()
                expect(person.created_at.toISO()).toBe('1970-01-01T00:00:05.000Z') // Fake person marker
                expect(person.force_upgrade).toBeUndefined()
            }
        })

        it('returns existing person with empty properties when person exists', async () => {
            const personUuid = new UUIDT().toString()

            await createPerson(hub, timestamp, { name: 'John' }, {}, {}, teamId, null, false, personUuid, {
                distinctId: pluginEvent.distinct_id,
            })

            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value
                expect(person.uuid).toBe(personUuid)
                expect(person.properties).toEqual({}) // Properties cleared for personless
                expect(person.force_upgrade).toBeUndefined() // No force upgrade yet
            }
        })

        it('checks batch result for personless distinct ID when no person exists', async () => {
            const getPersonlessBatchResultSpy = jest.spyOn(personsStore, 'getPersonlessBatchResult')

            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            // The batch step is responsible for the INSERT, processPersonlessStep just checks the result
            expect(getPersonlessBatchResultSpy).toHaveBeenCalledWith(teamId, pluginEvent.distinct_id)
        })

        it('returns fake person when batch result indicates no merge', async () => {
            // Mock batch result returning false (not merged)
            jest.spyOn(personsStore, 'getPersonlessBatchResult').mockReturnValue(false)

            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value
                expect(person.created_at.toISO()).toBe('1970-01-01T00:00:05.000Z') // Fake person
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

            // Event is at 02:15:00, person created at 02:00:00 -> more than 1 minute
            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value
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

            // Event is at 02:15:00, person created at 02:14:30 -> within 1 minute
            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value
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

            // Event is at 02:15:00, person created at 02:00:00 -> more than 1 minute, but team opted out
            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value
                expect(person.uuid).toBe(personUuid)
                expect(person.force_upgrade).toBeUndefined() // Not set due to opt-out
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

            // Mock fetchForChecking to return null initially (simulating no person found)
            jest.spyOn(personsStore, 'fetchForChecking').mockResolvedValueOnce(null)

            // Mock getPersonlessBatchResult to return true (indicating merge happened via batch step)
            jest.spyOn(personsStore, 'getPersonlessBatchResult').mockReturnValue(true)

            // Mock fetchForUpdate to return the actual person
            const fetchForUpdateSpy = jest.spyOn(personsStore, 'fetchForUpdate').mockResolvedValue(person)

            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(fetchForUpdateSpy).toHaveBeenCalledWith(teamId, pluginEvent.distinct_id)
        })
    })

    describe('forceDisablePersonProcessing', () => {
        it('skips all DB operations and returns fake person immediately when true', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')
            const getPersonlessBatchResultSpy = jest.spyOn(personsStore, 'getPersonlessBatchResult')

            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, true)

            expect(result.type).toBe(PipelineResultType.OK)
            if (isOkResult(result)) {
                const person = result.value
                expect(person.team_id).toBe(teamId)
                expect(person.properties).toEqual({})
                expect(person.created_at.toISO()).toBe('1970-01-01T00:00:05.000Z')
            }

            // Verify no database operations were performed
            expect(fetchForCheckingSpy).not.toHaveBeenCalled()
            expect(getPersonlessBatchResultSpy).not.toHaveBeenCalled()
        })

        it('performs normal processing when false', async () => {
            const fetchForCheckingSpy = jest.spyOn(personsStore, 'fetchForChecking')

            const result = await processPersonlessStep(pluginEvent, team, timestamp, personsStore, false)

            expect(result.type).toBe(PipelineResultType.OK)
            // Should perform database operations
            expect(fetchForCheckingSpy).toHaveBeenCalled()
        })

        it('works with different distinct IDs', async () => {
            const distinctIds = ['user-1', 'user-2', 'user-3']

            for (const distinctId of distinctIds) {
                const event = { ...pluginEvent, distinct_id: distinctId }
                const result = await processPersonlessStep(event, team, timestamp, personsStore, true)

                expect(result.type).toBe(PipelineResultType.OK)
                if (isOkResult(result)) {
                    expect(result.value.team_id).toBe(teamId)
                    expect(result.value.properties).toEqual({})
                }
            }
        })
    })
})
