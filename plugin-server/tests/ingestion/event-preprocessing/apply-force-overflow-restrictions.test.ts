import { applyForceOverflowRestrictions } from '../../../src/ingestion/event-preprocessing/apply-force-overflow-restrictions'
import { EventHeaders } from '../../../src/types'
import { EventIngestionRestrictionManager } from '../../../src/utils/event-ingestion-restriction-manager'

describe('applyForceOverflowRestrictions', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            shouldForceOverflow: jest.fn(),
            shouldSkipPerson: jest.fn(),
        } as unknown as EventIngestionRestrictionManager
    })

    it('returns shouldRedirect=false when not forcing overflow', () => {
        const headers: EventHeaders = {
            token: 'valid-token-123',
            distinct_id: 'user-456',
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = applyForceOverflowRestrictions(eventIngestionRestrictionManager, headers)

        expect(result).toEqual({ shouldRedirect: false })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('valid-token-123', 'user-456')
        // shouldSkipPerson should not be called if not forcing overflow
        expect(eventIngestionRestrictionManager.shouldSkipPerson).not.toHaveBeenCalled()
    })

    it('forces overflow and preserves partition locality when not skipping person', () => {
        const headers: EventHeaders = {
            token: 't-xyz',
            distinct_id: 'd-1',
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = applyForceOverflowRestrictions(eventIngestionRestrictionManager, headers)

        expect(result).toEqual({ shouldRedirect: true, preservePartitionLocality: true })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('t-xyz', 'd-1')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith('t-xyz', 'd-1')
    })

    it('forces overflow without preserving partition locality when skipping person', () => {
        const headers: EventHeaders = {
            token: 't-abc',
            distinct_id: 'd-2',
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = applyForceOverflowRestrictions(eventIngestionRestrictionManager, headers)

        expect(result).toEqual({ shouldRedirect: true, preservePartitionLocality: undefined })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('t-abc', 'd-2')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith('t-abc', 'd-2')
    })

    it('handles undefined headers', () => {
        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = applyForceOverflowRestrictions(eventIngestionRestrictionManager, undefined)

        expect(result).toEqual({ shouldRedirect: false })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(undefined, undefined)
    })

    it('handles empty headers', () => {
        const headers: EventHeaders = {}
        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = applyForceOverflowRestrictions(eventIngestionRestrictionManager, headers)

        expect(result).toEqual({ shouldRedirect: false })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(undefined, undefined)
    })
})
