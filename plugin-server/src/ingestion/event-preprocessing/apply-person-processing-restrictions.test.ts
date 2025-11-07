import { PipelineEvent, Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { ok } from '../pipelines/results'
import { createApplyPersonProcessingRestrictionsStep } from './apply-person-processing-restrictions'

describe('createApplyPersonProcessingRestrictionsStep', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager
    let step: ReturnType<typeof createApplyPersonProcessingRestrictionsStep>

    const createInput = (overrides: any = {}) => {
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
            } as PipelineEvent,
            team: {
                ...defaultTeam,
                ...overrides.team,
            } as Team,
        }
    }

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            shouldSkipPerson: jest.fn(),
        } as unknown as EventIngestionRestrictionManager

        step = createApplyPersonProcessingRestrictionsStep(eventIngestionRestrictionManager)
    })

    it('should not modify event if no skip conditions', async () => {
        const input = createInput({
            event: { token: 'valid-token-abc', distinct_id: 'user-123', properties: { defaultProp: 'defaultValue' } },
            team: { person_processing_opt_out: false },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties).toEqual({ defaultProp: 'defaultValue' })
        expect(input.event.token).toBe('valid-token-abc')
        expect(input.event.distinct_id).toBe('user-123')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith('valid-token-abc', 'user-123')
    })

    it('should set $process_person_profile to false if there is a restriction', async () => {
        const input = createInput({
            event: { token: 'restricted-token-def', distinct_id: 'restricted-user-456' },
            team: { person_processing_opt_out: false },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'restricted-token-def',
            'restricted-user-456'
        )
    })

    it('should set $process_person_profile to false if team opted out of person processing', async () => {
        const input = createInput({
            event: { token: 'opt-out-token-ghi', distinct_id: 'opt-out-user-789' },
            team: { person_processing_opt_out: true },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties?.$process_person_profile).toBe(false)
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'opt-out-token-ghi',
            'opt-out-user-789'
        )
    })

    it('should preserve existing properties when setting $process_person_profile', async () => {
        const input = createInput({
            event: {
                token: 'preserve-token-jkl',
                distinct_id: 'preserve-user-012',
                properties: { customProp: 'customValue', $set: { a: 1, b: 2 } },
            },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties).toMatchObject({
            customProp: 'customValue',
            $set: { a: 1, b: 2 },
            $process_person_profile: false,
        })
        expect(input.event.token).toBe('preserve-token-jkl')
        expect(input.event.distinct_id).toBe('preserve-user-012')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            'preserve-token-jkl',
            'preserve-user-012'
        )
    })

    it('should call shouldSkipPerson when token is undefined', async () => {
        const input = createInput({
            event: {
                token: undefined,
                distinct_id: 'undefined-token-user-999',
                properties: { customProp: 'customValue' },
            },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties).toEqual({ customProp: 'customValue' })
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            undefined,
            'undefined-token-user-999'
        )
    })

    it('should set $process_person_profile to false when token is undefined and shouldSkipPerson returns true', async () => {
        const input = createInput({
            event: {
                token: undefined,
                distinct_id: 'undefined-token-user-888',
                properties: { customProp: 'customValue' },
            },
        })
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(input.event.properties).toMatchObject({
            customProp: 'customValue',
            $process_person_profile: false,
        })
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            undefined,
            'undefined-token-user-888'
        )
    })
})
