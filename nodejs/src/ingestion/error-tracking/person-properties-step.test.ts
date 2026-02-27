import { DateTime } from 'luxon'

import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { InternalPerson } from '~/types'
import { PersonRepository } from '~/worker/ingestion/persons/repositories/person-repository'

import { PipelineResultType, isOkResult } from '../pipelines/results'
import { createPersonPropertiesReadOnlyStep } from './person-properties-step'

describe('createPersonPropertiesReadOnlyStep', () => {
    let mockPersonRepository: jest.Mocked<PersonRepository>
    let step: ReturnType<typeof createPersonPropertiesReadOnlyStep>

    const team = createTestTeam({ id: 123 })

    const createTestInternalPerson = (overrides: Partial<InternalPerson> = {}): InternalPerson => ({
        id: '1',
        uuid: 'person-uuid-123',
        team_id: 123,
        properties: { email: 'test@example.com', name: 'Test User' },
        is_user_id: null,
        is_identified: true,
        created_at: DateTime.utc(2024, 1, 1),
        version: 1,
        last_seen_at: null,
        properties_last_updated_at: {},
        properties_last_operation: null,
        ...overrides,
    })

    beforeEach(() => {
        mockPersonRepository = {
            fetchPerson: jest.fn(),
            fetchPersonsByDistinctIds: jest.fn(),
            countPersonsByProperties: jest.fn(),
            fetchPersonsByProperties: jest.fn(),
            createPerson: jest.fn(),
            updatePerson: jest.fn(),
            updatePersonAssertVersion: jest.fn(),
            updatePersonsBatch: jest.fn(),
            deletePerson: jest.fn(),
            addDistinctId: jest.fn(),
            addPersonlessDistinctId: jest.fn(),
            addPersonlessDistinctIdForMerge: jest.fn(),
            addPersonlessDistinctIdsBatch: jest.fn(),
            personPropertiesSize: jest.fn(),
            updateCohortsAndFeatureFlagsForMerge: jest.fn(),
            inTransaction: jest.fn(),
        }
        step = createPersonPropertiesReadOnlyStep(mockPersonRepository)
    })

    it('fetches person and passes it through when person exists', async () => {
        const event = createTestPluginEvent({
            distinct_id: 'user-123',
            event: '$exception',
            properties: { existing: 'property' },
        })
        const person = createTestInternalPerson()

        mockPersonRepository.fetchPerson.mockResolvedValueOnce(person)

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            // Event properties should NOT be modified (no $person_id/$person_properties added)
            expect(result.value.event.properties).toEqual({ existing: 'property' })
            // Person should be passed through for downstream steps
            expect(result.value.person).toEqual(person)
        }
        expect(mockPersonRepository.fetchPerson).toHaveBeenCalledWith(123, 'user-123', { useReadReplica: true })
    })

    it('returns null person when person not found', async () => {
        const event = createTestPluginEvent({
            distinct_id: 'unknown-user',
            event: '$exception',
            properties: { existing: 'property' },
        })

        mockPersonRepository.fetchPerson.mockResolvedValueOnce(undefined)

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({ existing: 'property' })
            expect(result.value.person).toBeNull()
        }
    })

    it('returns null person when distinct_id is missing', async () => {
        const event = createTestPluginEvent({
            distinct_id: '',
            event: '$exception',
            properties: { existing: 'property' },
        })

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({ existing: 'property' })
            expect(result.value.person).toBeNull()
        }
        expect(mockPersonRepository.fetchPerson).not.toHaveBeenCalled()
    })

    it('preserves original input structure', async () => {
        const event = createTestPluginEvent({
            distinct_id: 'user-123',
            event: '$exception',
            properties: { key: 'value' },
        })
        const person = createTestInternalPerson()

        mockPersonRepository.fetchPerson.mockResolvedValueOnce(person)

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.team).toBe(team)
            expect(result.value.event).toBe(event) // Same reference, unmodified
        }
    })

    it('uses read replica for performance', async () => {
        const event = createTestPluginEvent({
            distinct_id: 'user-123',
        })

        mockPersonRepository.fetchPerson.mockResolvedValueOnce(undefined)

        await step({ event, team })

        expect(mockPersonRepository.fetchPerson).toHaveBeenCalledWith(expect.any(Number), expect.any(String), {
            useReadReplica: true,
        })
    })
})
