import { applyPersonProcessingRestrictions } from '../../../src/ingestion/event-preprocessing/apply-person-processing-restrictions'
import { IncomingEventWithTeam } from '../../../src/types'
import { EventIngestionRestrictionManager } from '../../../src/utils/event-ingestion-restriction-manager'

describe('applyPersonProcessingRestrictions', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager

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
            ...overrides,
        } as IncomingEventWithTeam
    }

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            shouldSkipPerson: jest.fn(),
        } as unknown as EventIngestionRestrictionManager
    })

    it('should not modify event if no skip conditions', () => {
        const eventWithTeam = createEventWithTeam({
            event: { token: 'valid-token-abc', distinct_id: 'user-123', properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)

        expect(eventWithTeam.event.properties).toEqual({ defaultProp: 'defaultValue' })
        expect(eventWithTeam.event.token).toBe('valid-token-abc')
        expect(eventWithTeam.event.distinct_id).toBe('user-123')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith('valid-token-abc', 'user-123')
    })

    it('should set $process_person_profile to false if there is a restriction', () => {
        const eventWithTeam = createEventWithTeam({
            event: { token: 'restricted-token-def', distinct_id: 'restricted-user-456' },
            team: { person_processing_opt_out: false },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)

        expect(eventWithTeam.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'restricted-token-def',
            'restricted-user-456'
        )
    })

    it('should set $process_person_profile to false if team opted out of person processing', () => {
        const eventWithTeam = createEventWithTeam({
            event: { token: 'opt-out-token-ghi', distinct_id: 'opt-out-user-789' },
            team: { person_processing_opt_out: true },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)

        expect(eventWithTeam.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'opt-out-token-ghi',
            'opt-out-user-789'
        )
    })

    it('should preserve existing properties when setting $process_person_profile', () => {
        const eventWithTeam = createEventWithTeam({
            event: {
                token: 'preserve-token-jkl',
                distinct_id: 'preserve-user-012',
                properties: { customProp: 'customValue', $set: { a: 1, b: 2 } },
            },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)

        expect(eventWithTeam.event.properties).toMatchObject({
            customProp: 'customValue',
            $set: { a: 1, b: 2 },
            $process_person_profile: false,
        })
        expect(eventWithTeam.event.token).toBe('preserve-token-jkl')
        expect(eventWithTeam.event.distinct_id).toBe('preserve-user-012')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'preserve-token-jkl',
            'preserve-user-012'
        )
    })

    it('should call shouldSkipPerson when token is undefined', () => {
        const eventWithTeam = createEventWithTeam({
            event: {
                token: undefined,
                distinct_id: 'undefined-token-user-999',
                properties: { customProp: 'customValue' },
            },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)

        expect(eventWithTeam.event.properties).toEqual({ customProp: 'customValue' })
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            undefined,
            'undefined-token-user-999'
        )
    })

    it('should set $process_person_profile to false when token is undefined and shouldSkipPerson returns true', () => {
        const eventWithTeam = createEventWithTeam({
            event: {
                token: undefined,
                distinct_id: 'undefined-token-user-888',
                properties: { customProp: 'customValue' },
            },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)

        expect(eventWithTeam.event.properties).toMatchObject({
            customProp: 'customValue',
            $process_person_profile: false,
        })
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            undefined,
            'undefined-token-user-888'
        )
    })
})
