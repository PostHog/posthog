import { PluginEvent } from '@posthog/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { EventIngestionRestrictionManager, Restriction } from '../../utils/event-ingestion-restrictions'
import { ok } from '../pipelines/results'
import { createApplyPersonProcessingRestrictionsStep } from './apply-person-processing-restrictions'

describe('createApplyPersonProcessingRestrictionsStep', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager
    let step: ReturnType<typeof createApplyPersonProcessingRestrictionsStep>

    const createInput = (overrides: any = {}): { event: PluginEvent; team: Team; headers: EventHeaders } => {
        const defaultEvent = {
            token: 'default-token-123',
            distinct_id: 'default-user-456',
            properties: { defaultProp: 'defaultValue' },
            team_id: 1,
            ip: '127.0.0.1',
            site_url: 'https://example.com',
            now: '2020-02-23T02:15:00Z',
            event: 'test-event',
            uuid: '123e4567-e89b-12d3-a456-426614174000',
        }

        const defaultTeam = {
            person_processing_opt_out: false,
        }

        return {
            event: {
                ...defaultEvent,
                ...overrides.event,
            } as PluginEvent,
            team: {
                ...defaultTeam,
                ...overrides.team,
            } as unknown as Team,
            headers: overrides.headers ?? ({} as EventHeaders),
        }
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
            getAppliedRestrictions: jest.fn().mockReturnValue(new Set()),
        } as unknown as EventIngestionRestrictionManager

        step = createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager)
    })

    it('should not modify event if no skip conditions', async () => {
        const { event, team } = createInput({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({ token: 'valid-token-abc', distinct_id: 'user-123' })
        const input = { event, team, headers }

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties).toEqual({ defaultProp: 'defaultValue' })
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'valid-token-abc',
            expect.objectContaining({
                distinct_id: 'user-123',
            })
        )
    })

    it('should set $process_person_profile to false if there is a restriction', async () => {
        const { event, team } = createInput({
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({ token: 'restricted-token-def', distinct_id: 'restricted-user-456' })
        const input = { event, team, headers }
        jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
            new Set([Restriction.SKIP_PERSON_PROCESSING])
        )

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'restricted-token-def',
            expect.objectContaining({
                distinct_id: 'restricted-user-456',
            })
        )
    })

    it('should set $process_person_profile to false if team opted out of person processing', async () => {
        const { event, team } = createInput({
            team: { person_processing_opt_out: true },
        })
        const headers = createHeaders({ token: 'opt-out-token-ghi', distinct_id: 'opt-out-user-789' })
        const input = { event, team, headers }

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'opt-out-token-ghi',
            expect.objectContaining({
                distinct_id: 'opt-out-user-789',
            })
        )
    })

    it('should preserve existing properties when setting $process_person_profile', async () => {
        const { event, team } = createInput({
            event: {
                properties: { customProp: 'customValue', $set: { a: 1, b: 2 } },
            },
        })
        const headers = createHeaders({ token: 'preserve-token-jkl', distinct_id: 'preserve-user-012' })
        const input = { event, team, headers }
        jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
            new Set([Restriction.SKIP_PERSON_PROCESSING])
        )

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties).toMatchObject({
            customProp: 'customValue',
            $set: { a: 1, b: 2 },
            $process_person_profile: false,
        })
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'preserve-token-jkl',
            expect.objectContaining({
                distinct_id: 'preserve-user-012',
            })
        )
    })

    it('should call getAppliedRestrictions when token is undefined', async () => {
        const { event, team } = createInput({
            event: {
                properties: { customProp: 'customValue' },
            },
        })
        const headers = createHeaders({ token: undefined, distinct_id: 'undefined-token-user-999' })
        const input = { event, team, headers }

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties).toEqual({ customProp: 'customValue' })
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            undefined,
            expect.objectContaining({
                distinct_id: 'undefined-token-user-999',
            })
        )
    })

    it('should set $process_person_profile to false when token is undefined and restriction is applied', async () => {
        const { event, team } = createInput({
            event: {
                properties: { customProp: 'customValue' },
            },
        })
        const headers = createHeaders({ token: undefined, distinct_id: 'undefined-token-user-888' })
        const input = { event, team, headers }
        jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
            new Set([Restriction.SKIP_PERSON_PROCESSING])
        )

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties).toMatchObject({
            customProp: 'customValue',
            $process_person_profile: false,
        })
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            undefined,
            expect.objectContaining({
                distinct_id: 'undefined-token-user-888',
            })
        )
    })

    it('should pass session_id from headers to getAppliedRestrictions', async () => {
        const { event, team } = createInput({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            session_id: 'session-456',
        })
        const input = { event, team, headers }

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'valid-token-abc',
            expect.objectContaining({
                distinct_id: 'user-123',
                session_id: 'session-456',
            })
        )
    })

    it('should pass event name from headers to getAppliedRestrictions', async () => {
        const { event, team } = createInput({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            event: '$pageview',
        })
        const input = { event, team, headers }

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'valid-token-abc',
            expect.objectContaining({
                distinct_id: 'user-123',
                event: '$pageview',
            })
        )
    })

    it('should pass uuid from headers to getAppliedRestrictions', async () => {
        const { event, team } = createInput({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            uuid: 'event-uuid-789',
        })
        const input = { event, team, headers }

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'valid-token-abc',
            expect.objectContaining({
                distinct_id: 'user-123',
                uuid: 'event-uuid-789',
            })
        )
    })

    it('should skip person processing when session_id is restricted', async () => {
        const { event, team } = createInput({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            session_id: 'restricted-session',
        })
        const input = { event, team, headers }
        jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
            new Set([Restriction.SKIP_PERSON_PROCESSING])
        )

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'valid-token-abc',
            expect.objectContaining({
                distinct_id: 'user-123',
                session_id: 'restricted-session',
            })
        )
    })

    it('should skip person processing when event_name is restricted', async () => {
        const { event, team } = createInput({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            event: '$restricted_event',
        })
        const input = { event, team, headers }
        jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
            new Set([Restriction.SKIP_PERSON_PROCESSING])
        )

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'valid-token-abc',
            expect.objectContaining({
                distinct_id: 'user-123',
                event: '$restricted_event',
            })
        )
    })

    it('should skip person processing when uuid is restricted', async () => {
        const { event, team } = createInput({
            event: { properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        const headers = createHeaders({
            token: 'valid-token-abc',
            distinct_id: 'user-123',
            uuid: 'restricted-uuid-789',
        })
        const input = { event, team, headers }
        jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
            new Set([Restriction.SKIP_PERSON_PROCESSING])
        )

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
            'valid-token-abc',
            expect.objectContaining({
                distinct_id: 'user-123',
                uuid: 'restricted-uuid-789',
            })
        )
    })
})
