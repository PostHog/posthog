import { drop, isDropResult, isOkResult, ok } from '../../../../ingestion/pipelines/results'
import { EventIngestionRestrictionManager } from '../../../../utils/event-ingestion-restriction-manager'
import { SessionRecordingIngesterMetrics } from '../metrics'
import { createTestMessage } from '../test-helpers'
import { createApplyDropRestrictionsStep } from './apply-drop-restrictions'

jest.mock('../metrics', () => ({
    SessionRecordingIngesterMetrics: {
        observeDroppedByRestrictions: jest.fn(),
    },
}))

describe('apply-drop-restrictions', () => {
    let mockRestrictionManager: jest.Mocked<EventIngestionRestrictionManager>

    beforeEach(() => {
        jest.clearAllMocks()
        mockRestrictionManager = {
            shouldDropEvent: jest.fn(),
        } as any
    })

    it('should return ok when shouldDropEvent returns false', async () => {
        mockRestrictionManager.shouldDropEvent.mockReturnValue(false)
        const step = createApplyDropRestrictionsStep(mockRestrictionManager)

        const message = createTestMessage()
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        expect(mockRestrictionManager.shouldDropEvent).toHaveBeenCalledWith('test-token', 'user-123')
        expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).not.toHaveBeenCalled()
    })

    it('should return drop when shouldDropEvent returns true', async () => {
        mockRestrictionManager.shouldDropEvent.mockReturnValue(true)
        const step = createApplyDropRestrictionsStep(mockRestrictionManager)

        const message = createTestMessage()
        const headers = { token: 'blocked-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isDropResult(result)).toBe(true)
        expect(result).toEqual(drop('blocked_token'))
        expect(mockRestrictionManager.shouldDropEvent).toHaveBeenCalledWith('blocked-token', 'user-123')
        expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).toHaveBeenCalledWith(1)
    })

    it('should handle undefined token', async () => {
        mockRestrictionManager.shouldDropEvent.mockReturnValue(false)
        const step = createApplyDropRestrictionsStep(mockRestrictionManager)

        const message = createTestMessage()
        const headers = { distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        expect(mockRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(undefined, 'user-123')
    })

    it('should handle undefined distinct_id', async () => {
        mockRestrictionManager.shouldDropEvent.mockReturnValue(false)
        const step = createApplyDropRestrictionsStep(mockRestrictionManager)

        const message = createTestMessage()
        const headers = { token: 'test-token', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        expect(mockRestrictionManager.shouldDropEvent).toHaveBeenCalledWith('test-token', undefined)
    })

    it('should return message unchanged when ok', async () => {
        mockRestrictionManager.shouldDropEvent.mockReturnValue(false)
        const step = createApplyDropRestrictionsStep(mockRestrictionManager)

        const message = createTestMessage({ partition: 5, offset: 100 })
        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ message, headers })

        expect(isOkResult(result)).toBe(true)
        expect(result).toEqual(ok({ message, headers }))
    })
})
