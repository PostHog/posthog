import { Message } from 'node-rdkafka'

import { applyForceOverflowRestrictions } from '../../../src/ingestion/event-preprocessing/apply-force-overflow-restrictions'
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
        const message = {
            headers: [{ token: Buffer.from('valid-token-123') }, { distinct_id: Buffer.from('user-456') }],
        } as unknown as Message

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = applyForceOverflowRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toEqual({ shouldRedirect: false })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('valid-token-123', 'user-456')
        // shouldSkipPerson should not be called if not forcing overflow
        expect(eventIngestionRestrictionManager.shouldSkipPerson).not.toHaveBeenCalled()
    })

    it('forces overflow and preserves partition locality when not skipping person', () => {
        const message = {
            headers: [{ token: Buffer.from('t-xyz') }, { distinct_id: Buffer.from('d-1') }],
        } as unknown as Message

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = applyForceOverflowRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toEqual({ shouldRedirect: true, preservePartitionLocality: true })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('t-xyz', 'd-1')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith('t-xyz', 'd-1')
    })

    it('forces overflow without preserving partition locality when skipping person', () => {
        const message = {
            headers: [{ token: Buffer.from('t-abc') }, { distinct_id: Buffer.from('d-2') }],
        } as unknown as Message

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = applyForceOverflowRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toEqual({ shouldRedirect: true, preservePartitionLocality: undefined })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('t-abc', 'd-2')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith('t-abc', 'd-2')
    })

    it('handles message without headers', () => {
        const message = {} as unknown as Message
        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = applyForceOverflowRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toEqual({ shouldRedirect: false })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(undefined, undefined)
    })

    it('handles message with empty headers', () => {
        const message = { headers: [] } as unknown as Message
        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = applyForceOverflowRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toEqual({ shouldRedirect: false })
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(undefined, undefined)
    })
})
