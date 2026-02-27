import { DateTime } from 'luxon'

import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { EventHeaders, Person } from '~/types'

import { PipelineResultType, isOkResult } from '../pipelines/results'
import { createErrorTrackingPrepareEventStep } from './prepare-event-step'

describe('createErrorTrackingPrepareEventStep', () => {
    let step: ReturnType<typeof createErrorTrackingPrepareEventStep>

    const team = createTestTeam({ id: 123, project_id: 456 as any })

    const createTestHeaders = (overrides: Partial<EventHeaders> = {}): EventHeaders => ({
        force_disable_person_processing: false,
        historical_migration: false,
        ...overrides,
    })

    const createTestPerson = (overrides: Partial<Person> = {}): Person => ({
        team_id: 123,
        uuid: 'person-uuid-123',
        properties: { email: 'test@example.com', name: 'Test User' },
        created_at: DateTime.utc(2024, 1, 1),
        ...overrides,
    })

    beforeEach(() => {
        step = createErrorTrackingPrepareEventStep()
    })

    it('converts PluginEvent to PreIngestionEvent format', async () => {
        const event = createTestPluginEvent({
            uuid: 'event-uuid-123',
            event: '$exception',
            distinct_id: 'user-123',
            timestamp: '2024-01-15T10:30:00.000Z',
            properties: { $exception_list: [{ type: 'Error', value: 'Test' }] },
        })
        const person = createTestPerson()

        const result = await step({ event, team, person, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent).toEqual({
                eventUuid: 'event-uuid-123',
                event: '$exception',
                teamId: 123,
                projectId: 456,
                distinctId: 'user-123',
                properties: { $exception_list: [{ type: 'Error', value: 'Test' }] },
                timestamp: '2024-01-15T10:30:00.000Z',
            })
        }
    })

    it('uses existing person when provided', async () => {
        const event = createTestPluginEvent({ event: '$exception' })
        const person = createTestPerson({ uuid: 'existing-person-uuid' })

        const result = await step({ event, team, person, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.person.uuid).toBe('existing-person-uuid')
            expect(result.value.person.properties).toEqual({ email: 'test@example.com', name: 'Test User' })
        }
    })

    it('creates placeholder person when person is null', async () => {
        const event = createTestPluginEvent({ event: '$exception' })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.person).toBeDefined()
            expect(result.value.person.team_id).toBe(123)
            expect(result.value.person.uuid).toMatch(/^[0-9a-f-]{36}$/)
            expect(result.value.person.properties).toEqual({})
            expect(result.value.person.created_at).toBeDefined()
        }
    })

    it('always sets processPerson to true', async () => {
        const event = createTestPluginEvent({ event: '$exception' })

        // With person
        const resultWithPerson = await step({ event, team, person: createTestPerson(), headers: createTestHeaders() })
        expect(isOkResult(resultWithPerson) && resultWithPerson.value.processPerson).toBe(true)

        // Without person
        const resultWithoutPerson = await step({ event, team, person: null, headers: createTestHeaders() })
        expect(isOkResult(resultWithoutPerson) && resultWithoutPerson.value.processPerson).toBe(true)
    })

    it('extracts historical_migration flag from headers when true', async () => {
        const event = createTestPluginEvent({ event: '$exception' })

        const result = await step({
            event,
            team,
            person: null,
            headers: createTestHeaders({ historical_migration: true }),
        })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.historicalMigration).toBe(true)
        }
    })

    it('defaults historical_migration to false when not in headers', async () => {
        const event = createTestPluginEvent({ event: '$exception' })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.historicalMigration).toBe(false)
        }
    })

    it('uses event.now as timestamp when timestamp is missing', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            timestamp: undefined,
            now: '2024-01-20T12:00:00.000Z',
        })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent.timestamp).toBe('2024-01-20T12:00:00.000Z')
        }
    })

    it('defaults properties to empty object when null', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: null as any,
        })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent.properties).toEqual({})
        }
    })

    it('preserves additional fields from input via type inheritance', async () => {
        const event = createTestPluginEvent({ event: '$exception' })

        // Create input with additional fields that should be preserved
        const inputWithExtras = {
            event,
            team,
            person: null,
            headers: createTestHeaders(),
            message: { topic: 'test-topic', partition: 0 } as any,
            customField: 'should-be-preserved',
        }

        const result = await step(inputWithExtras)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            // Additional fields should be preserved in output
            expect((result.value as any).message).toEqual({ topic: 'test-topic', partition: 0 })
            expect((result.value as any).customField).toBe('should-be-preserved')

            // Original fields should be transformed/removed
            expect((result.value as any).event).toBeUndefined()
            expect((result.value as any).team).toBeUndefined()
        }
    })

    it('removes event and team from output but adds preparedEvent', async () => {
        const event = createTestPluginEvent({ event: '$exception' })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            // These should not be in output
            expect('event' in result.value).toBe(false)
            expect('team' in result.value).toBe(false)

            // These should be in output
            expect(result.value.preparedEvent).toBeDefined()
            expect(result.value.person).toBeDefined()
            expect(result.value.processPerson).toBe(true)
            expect(result.value.historicalMigration).toBeDefined()
        }
    })
})
