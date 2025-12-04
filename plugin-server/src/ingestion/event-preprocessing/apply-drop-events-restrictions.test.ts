import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { drop, ok } from '../pipelines/results'
import { createApplyDropRestrictionsStep } from './apply-drop-events-restrictions'

describe('createApplyDropRestrictionsStep', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager
    let step: ReturnType<typeof createApplyDropRestrictionsStep>

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            applyDropEventsRestrictions: jest.fn(),
            shouldDropEvent: jest.fn(),
        } as unknown as EventIngestionRestrictionManager

        step = createApplyDropRestrictionsStep(eventIngestionRestrictionManager)
    })

    it('should return success when token is present and not dropped', async () => {
        const input = {
            message: {} as any,
            headers: {
                token: 'valid-token-123',
                distinct_id: 'user-456',
                force_disable_person_processing: false,
            },
        }
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
            'valid-token-123',
            'user-456',
            undefined
        )
    })

    it('should return drop when token is present but should be dropped', async () => {
        const input = {
            message: {} as any,
            headers: {
                token: 'blocked-token-abc',
                distinct_id: 'blocked-user-def',
                force_disable_person_processing: false,
            },
        }
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(drop('blocked_token'))
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
            'blocked-token-abc',
            'blocked-user-def',
            undefined
        )
    })

    it('should handle undefined headers', async () => {
        const input = {
            message: {} as any,
            headers: {} as EventHeaders,
        }
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(undefined, undefined, undefined)
    })

    it('should handle empty headers', async () => {
        const input = {
            message: {} as any,
            headers: {
                force_disable_person_processing: false,
            },
        }
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(undefined, undefined, undefined)
    })

    it('should pass session_id when present in headers', async () => {
        const input = {
            message: {} as any,
            headers: {
                token: 'valid-token-123',
                distinct_id: 'user-456',
                session_id: 'session-789',
                force_disable_person_processing: false,
            },
        }
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
            'valid-token-123',
            'user-456',
            'session-789'
        )
    })

    it('should drop event when session_id is restricted', async () => {
        const input = {
            message: {} as any,
            headers: {
                token: 'valid-token-123',
                distinct_id: 'user-456',
                session_id: 'blocked-session-789',
                force_disable_person_processing: false,
            },
        }
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(drop('blocked_token'))
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
            'valid-token-123',
            'user-456',
            'blocked-session-789'
        )
    })
})
