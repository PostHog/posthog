import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { ok } from '../pipelines/results'
import { createApplyPersonProcessingRestrictionsStep } from './apply-person-processing-restrictions'

describe('createApplyPersonProcessingRestrictionsStep', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager
    let step: ReturnType<typeof createApplyPersonProcessingRestrictionsStep>

    const createEventWithTeam = (overrides: any = {}): IncomingEventWithTeam => {
        const defaultEvent = {
            token: 'default-token-123',
            distinct_id: 'default-user-456',
            properties: { defaultProp: 'defaultValue' },
        }

        const defaultTeam = {
            person_processing_opt_out: false,
        }

        return {
            event: {
                ...defaultEvent,
                ...overrides.event,
            },
            team: {
                ...defaultTeam,
                ...overrides.team,
            } as unknown as any,
            message: {} as any,
            headers: {} as EventHeaders,
            ...overrides,
        } as IncomingEventWithTeam
    }

    const createHeaders = (overrides: Partial<EventHeaders> = {}): EventHeaders => ({
        token: 'default-token',
        distinct_id: 'default-distinct-id',
        force_disable_person_processing: false,
        historical_migration: false,
        ...overrides,
    })

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            shouldSkipPerson: jest.fn(),
        } as unknown as EventIngestionRestrictionManager

        step = createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager)
    })

    it('should not modify event if no skip conditions', async () => {
        const eventWithTeam = createEventWithTeam({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({ token: 'valid-token-abc', distinct_id: 'user-123' })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties).toEqual({ defaultProp: 'defaultValue' })
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'valid-token-abc',
            'user-123',
            undefined,
            undefined,
            undefined
        )
    })

    it('should set $process_person_profile to false if there is a restriction', async () => {
        const eventWithTeam = createEventWithTeam({
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({ token: 'restricted-token-def', distinct_id: 'restricted-user-456' })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'restricted-token-def',
            'restricted-user-456',
            undefined,
            undefined,
            undefined
        )
    })

    it('should set $process_person_profile to false if team opted out of person processing', async () => {
        const eventWithTeam = createEventWithTeam({
            team: { person_processing_opt_out: true },
        })
        const headers = createHeaders({ token: 'opt-out-token-ghi', distinct_id: 'opt-out-user-789' })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'opt-out-token-ghi',
            'opt-out-user-789',
            undefined,
            undefined,
            undefined
        )
    })

    it('should preserve existing properties when setting $process_person_profile', async () => {
        const eventWithTeam = createEventWithTeam({
            event: {
                properties: { customProp: 'customValue', $set: { a: 1, b: 2 } },
            },
        })
        const headers = createHeaders({ token: 'preserve-token-jkl', distinct_id: 'preserve-user-012' })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties).toMatchObject({
            customProp: 'customValue',
            $set: { a: 1, b: 2 },
            $process_person_profile: false,
        })
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'preserve-token-jkl',
            'preserve-user-012',
            undefined,
            undefined,
            undefined
        )
    })

    it('should call shouldSkipPerson when token is undefined', async () => {
        const eventWithTeam = createEventWithTeam({
            event: {
                properties: { customProp: 'customValue' },
            },
        })
        const headers = createHeaders({ token: undefined, distinct_id: 'undefined-token-user-999' })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties).toEqual({ customProp: 'customValue' })
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            undefined,
            'undefined-token-user-999',
            undefined,
            undefined,
            undefined
        )
    })

    it('should set $process_person_profile to false when token is undefined and shouldSkipPerson returns true', async () => {
        const eventWithTeam = createEventWithTeam({
            event: {
                properties: { customProp: 'customValue' },
            },
        })
        const headers = createHeaders({ token: undefined, distinct_id: 'undefined-token-user-888' })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties).toMatchObject({
            customProp: 'customValue',
            $process_person_profile: false,
        })
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            undefined,
            'undefined-token-user-888',
            undefined,
            undefined,
            undefined
        )
    })

    it('should pass session_id from headers to shouldSkipPerson', async () => {
        const eventWithTeam = createEventWithTeam({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            session_id: 'session-456',
        })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'valid-token-abc',
            'user-123',
            'session-456',
            undefined,
            undefined
        )
    })

    it('should pass event name from headers to shouldSkipPerson', async () => {
        const eventWithTeam = createEventWithTeam({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            event: '$pageview',
        })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'valid-token-abc',
            'user-123',
            undefined,
            '$pageview',
            undefined
        )
    })

    it('should pass uuid from headers to shouldSkipPerson', async () => {
        const eventWithTeam = createEventWithTeam({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            uuid: 'event-uuid-789',
        })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'valid-token-abc',
            'user-123',
            undefined,
            undefined,
            'event-uuid-789'
        )
    })

    it('should skip person processing when session_id is restricted', async () => {
        const eventWithTeam = createEventWithTeam({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            session_id: 'restricted-session',
        })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'valid-token-abc',
            'user-123',
            'restricted-session',
            undefined,
            undefined
        )
    })

    it('should skip person processing when event_name is restricted', async () => {
        const eventWithTeam = createEventWithTeam({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            event: '$restricted_event',
        })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'valid-token-abc',
            'user-123',
            undefined,
            '$restricted_event',
            undefined
        )
    })

    it('should skip person processing when uuid is restricted', async () => {
        const eventWithTeam = createEventWithTeam({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            uuid: 'restricted-uuid-789',
        })
        const input = { eventWithTeam, headers }
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.eventWithTeam.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'valid-token-abc',
            'user-123',
            undefined,
            undefined,
            'restricted-uuid-789'
        )
    })
})
