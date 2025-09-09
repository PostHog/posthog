import { applyDropEventsRestrictions } from '../../../src/ingestion/event-preprocessing/apply-drop-events-restrictions'
import { EventHeaders } from '../../../src/types'
import { EventIngestionRestrictionManager } from '../../../src/utils/event-ingestion-restriction-manager'

describe('applyDropEventsRestrictions', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            applyDropEventsRestrictions: jest.fn(),
            shouldDropEvent: jest.fn(),
        } as unknown as EventIngestionRestrictionManager
    })

    it('should return false when token is present and not dropped', () => {
        const headers: EventHeaders = {
            token: 'valid-token-123',
            distinct_id: 'user-456',
        }
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = applyDropEventsRestrictions(eventIngestionRestrictionManager, headers)

        expect(result).toBe(false)
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith('valid-token-123', 'user-456')
    })

    it('should return true when token is present but should be dropped', () => {
        const headers: EventHeaders = {
            token: 'blocked-token-abc',
            distinct_id: 'blocked-user-def',
        }
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(true)

        const result = applyDropEventsRestrictions(eventIngestionRestrictionManager, headers)

        expect(result).toBe(true)
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
            'blocked-token-abc',
            'blocked-user-def'
        )
    })

    it('should handle undefined headers', () => {
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = applyDropEventsRestrictions(eventIngestionRestrictionManager, undefined)

        expect(result).toBe(false)
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(undefined, undefined)
    })

    it('should handle empty headers', () => {
        const headers: EventHeaders = {}
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = applyDropEventsRestrictions(eventIngestionRestrictionManager, headers)

        expect(result).toBe(false)
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(undefined, undefined)
    })
})
