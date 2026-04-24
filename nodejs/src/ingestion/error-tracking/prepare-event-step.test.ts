import { DateTime } from 'luxon'

import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { EventHeaders, Person } from '~/types'

import { BLOAT_PROPERTIES } from '../event-processing/strip-bloat-properties'
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
            expect(result.value.person).toBeDefined()
            expect(result.value.person?.uuid).toBe('existing-person-uuid')
            expect(result.value.person?.properties).toEqual({ email: 'test@example.com', name: 'Test User' })
        }
    })

    it('returns undefined person when person is null', async () => {
        const event = createTestPluginEvent({ event: '$exception' })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.person).toBeUndefined()
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

    it('uses pre-validated timestamp from cymbal step', async () => {
        // Timestamp validation happens in the cymbal processing step before this step.
        // The prepare step expects event.timestamp to already be validated and set.
        const event = createTestPluginEvent({
            event: '$exception',
            timestamp: '2024-01-20T12:00:00.000Z',
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

    it('should delete $ip when team.anonymize_ips is true', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: { $ip: '1.2.3.4', other: 'kept' },
        })
        const anonymizedTeam = createTestTeam({ id: 123, project_id: 456 as any, anonymize_ips: true })

        const result = await step({ event, team: anonymizedTeam, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent.properties['$ip']).toBeUndefined()
            expect(result.value.preparedEvent.properties['other']).toBe('kept')
        }
    })

    it('should strip bloat properties from $exception events', async () => {
        const bloat = Object.fromEntries([...BLOAT_PROPERTIES].map((key) => [key, { heavy: 'cache-blob' }]))
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                ...bloat,
                $exception_list: [{ type: 'Error', value: 'Test' }],
            },
        })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent.properties).toEqual({
                $exception_list: [{ type: 'Error', value: 'Test' }],
            })
        }
    })

    it('should keep $ip when team.anonymize_ips is false', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: { $ip: '1.2.3.4' },
        })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent.properties['$ip']).toBe('1.2.3.4')
        }
    })

    it('removes $set from properties to prevent incorrect person_properties merging', async () => {
        // Error tracking events ($exception) are in NO_PERSON_UPDATE_EVENTS, so person
        // updates are never written. However, createEvent() merges $set into person_properties
        // when processPerson=true. By removing $set here, we ensure person_properties only
        // contains actual DB values, matching Cymbal's behavior.
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test' }],
                $set: { $geoip_country_name: 'Sweden', email: 'new@example.com' },
                other_prop: 'preserved',
            },
        })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent.properties).toEqual({
                $exception_list: [{ type: 'Error', value: 'Test' }],
                other_prop: 'preserved',
            })
            expect(result.value.preparedEvent.properties.$set).toBeUndefined()
        }
    })

    it('removes $set_once from properties to prevent incorrect person_properties merging', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test' }],
                $set_once: { first_seen: '2024-01-01' },
                other_prop: 'preserved',
            },
        })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent.properties).toEqual({
                $exception_list: [{ type: 'Error', value: 'Test' }],
                other_prop: 'preserved',
            })
            expect(result.value.preparedEvent.properties.$set_once).toBeUndefined()
        }
    })

    it('removes both $set and $set_once when both are present', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test' }],
                $set: { email: 'new@example.com' },
                $set_once: { first_seen: '2024-01-01' },
            },
        })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.preparedEvent.properties).toEqual({
                $exception_list: [{ type: 'Error', value: 'Test' }],
            })
            expect(result.value.preparedEvent.properties.$set).toBeUndefined()
            expect(result.value.preparedEvent.properties.$set_once).toBeUndefined()
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

            // event should be removed, team should be preserved for downstream steps
            expect((result.value as any).event).toBeUndefined()
            expect((result.value as any).team).toBeDefined()
        }
    })

    it('removes event from output but preserves team and adds preparedEvent', async () => {
        const event = createTestPluginEvent({ event: '$exception' })

        const result = await step({ event, team, person: null, headers: createTestHeaders() })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            // event should not be in output
            expect('event' in result.value).toBe(false)

            // team should be preserved for downstream steps (e.g., read-only process groups)
            expect('team' in result.value).toBe(true)
            expect(result.value.team).toEqual(team)

            // These should be in output
            expect(result.value.preparedEvent).toBeDefined()
            expect(result.value.person).toBeUndefined() // null input becomes undefined
            expect(result.value.processPerson).toBe(true)
            expect(result.value.historicalMigration).toBeDefined()
        }
    })
})
