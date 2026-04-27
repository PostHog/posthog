import { DateTime } from 'luxon'

import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { InternalPerson } from '~/types'
import {
    InternalPersonWithDistinctId,
    PersonRepository,
} from '~/worker/ingestion/persons/repositories/person-repository'

import { PipelineResultType, isOkResult } from '../pipelines/results'
import { createFetchPersonBatchStep } from './person-properties-step'

describe('createFetchPersonBatchStep', () => {
    let mockPersonRepository: jest.Mocked<PersonRepository>
    let step: ReturnType<typeof createFetchPersonBatchStep>

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
            fetchPersonsByPersonIds: jest.fn(),
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
        step = createFetchPersonBatchStep(mockPersonRepository)
    })

    it('returns empty array for empty input', async () => {
        const results = await step([])

        expect(results).toEqual([])
        expect(mockPersonRepository.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
    })

    it('fetches persons in batch and maps them to inputs', async () => {
        const event1 = createTestPluginEvent({
            distinct_id: 'user-1',
            event: '$exception',
            properties: { idx: 1 },
        })
        const event2 = createTestPluginEvent({
            distinct_id: 'user-2',
            event: '$exception',
            properties: { idx: 2 },
        })
        const person1: InternalPersonWithDistinctId = {
            ...createTestInternalPerson({ uuid: 'person-1' }),
            distinct_id: 'user-1',
        }
        const person2: InternalPersonWithDistinctId = {
            ...createTestInternalPerson({ uuid: 'person-2' }),
            distinct_id: 'user-2',
        }

        mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValueOnce([person1, person2])

        const results = await step([
            { event: event1, team },
            { event: event2, team },
        ])

        expect(results).toHaveLength(2)
        expect(results[0].type).toBe(PipelineResultType.OK)
        expect(results[1].type).toBe(PipelineResultType.OK)
        if (isOkResult(results[0])) {
            expect(results[0].value.person?.uuid).toBe('person-1')
        }
        if (isOkResult(results[1])) {
            expect(results[1].value.person?.uuid).toBe('person-2')
        }
        expect(mockPersonRepository.fetchPersonsByDistinctIds).toHaveBeenCalledWith(
            [
                { teamId: 123, distinctId: 'user-1' },
                { teamId: 123, distinctId: 'user-2' },
            ],
            true // useReadReplica
        )
    })

    it('returns null person when person not found', async () => {
        const event = createTestPluginEvent({
            distinct_id: 'unknown-user',
            event: '$exception',
            properties: { existing: 'property' },
        })

        mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValueOnce([])

        const results = await step([{ event, team }])

        expect(results).toHaveLength(1)
        expect(results[0].type).toBe(PipelineResultType.OK)
        if (isOkResult(results[0])) {
            expect(results[0].value.event.properties).toEqual({ existing: 'property' })
            expect(results[0].value.person).toBeNull()
        }
    })

    it('returns null person when distinct_id is missing', async () => {
        const event = createTestPluginEvent({
            distinct_id: '',
            event: '$exception',
            properties: { existing: 'property' },
        })

        const results = await step([{ event, team }])

        expect(results).toHaveLength(1)
        expect(results[0].type).toBe(PipelineResultType.OK)
        if (isOkResult(results[0])) {
            expect(results[0].value.event.properties).toEqual({ existing: 'property' })
            expect(results[0].value.person).toBeNull()
        }
        expect(mockPersonRepository.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
    })

    it('handles mix of found and not found persons', async () => {
        const event1 = createTestPluginEvent({
            distinct_id: 'user-found',
            event: '$exception',
        })
        const event2 = createTestPluginEvent({
            distinct_id: 'user-not-found',
            event: '$exception',
        })
        const person: InternalPersonWithDistinctId = {
            ...createTestInternalPerson(),
            distinct_id: 'user-found',
        }

        mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValueOnce([person])

        const results = await step([
            { event: event1, team },
            { event: event2, team },
        ])

        expect(results).toHaveLength(2)
        if (isOkResult(results[0])) {
            expect(results[0].value.person).not.toBeNull()
        }
        if (isOkResult(results[1])) {
            expect(results[1].value.person).toBeNull()
        }
    })

    it('handles events with empty distinct_id mixed with valid ones', async () => {
        const eventWithDistinctId = createTestPluginEvent({
            distinct_id: 'user-123',
            event: '$exception',
        })
        const eventWithoutDistinctId = createTestPluginEvent({
            distinct_id: '',
            event: '$exception',
        })
        const person: InternalPersonWithDistinctId = {
            ...createTestInternalPerson(),
            distinct_id: 'user-123',
        }

        mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValueOnce([person])

        const results = await step([
            { event: eventWithDistinctId, team },
            { event: eventWithoutDistinctId, team },
        ])

        expect(results).toHaveLength(2)
        if (isOkResult(results[0])) {
            expect(results[0].value.person).not.toBeNull()
        }
        if (isOkResult(results[1])) {
            expect(results[1].value.person).toBeNull()
        }
        // Should only query for the event with distinct_id
        expect(mockPersonRepository.fetchPersonsByDistinctIds).toHaveBeenCalledWith(
            [{ teamId: 123, distinctId: 'user-123' }],
            true
        )
    })

    it('preserves original input structure', async () => {
        const event = createTestPluginEvent({
            distinct_id: 'user-123',
            event: '$exception',
            properties: { key: 'value' },
        })
        const person: InternalPersonWithDistinctId = {
            ...createTestInternalPerson(),
            distinct_id: 'user-123',
        }

        mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValueOnce([person])

        const results = await step([{ event, team }])

        expect(results).toHaveLength(1)
        if (isOkResult(results[0])) {
            expect(results[0].value.team).toBe(team)
            expect(results[0].value.event).toBe(event) // Same reference, unmodified
        }
    })
})
