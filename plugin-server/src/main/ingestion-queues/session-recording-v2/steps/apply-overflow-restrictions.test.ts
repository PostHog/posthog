import { isOkResult, isRedirectResult, ok, redirect } from '../../../../ingestion/pipelines/results'
import { EventHeaders } from '../../../../types'
import { EventIngestionRestrictionManager } from '../../../../utils/event-ingestion-restriction-manager'
import { SessionRecordingIngesterMetrics } from '../metrics'
import { createApplyOverflowRestrictionsStep } from './apply-overflow-restrictions'

jest.mock('../metrics', () => ({
    SessionRecordingIngesterMetrics: {
        observeOverflowedByRestrictions: jest.fn(),
    },
}))

describe('apply-overflow-restrictions', () => {
    let mockRestrictionManager: jest.Mocked<EventIngestionRestrictionManager>
    const overflowTopic = 'session_recording_events_overflow'

    beforeEach(() => {
        jest.clearAllMocks()
        mockRestrictionManager = {
            shouldForceOverflow: jest.fn(),
        } as any
    })

    it('should return ok when shouldForceOverflow returns false', async () => {
        mockRestrictionManager.shouldForceOverflow.mockReturnValue(false)
        const step = createApplyOverflowRestrictionsStep(mockRestrictionManager, overflowTopic, false)

        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ headers })

        expect(isOkResult(result)).toBe(true)
        expect(mockRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('test-token', 'user-123')
        expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).not.toHaveBeenCalled()
    })

    it('should return redirect when shouldForceOverflow returns true', async () => {
        mockRestrictionManager.shouldForceOverflow.mockReturnValue(true)
        const step = createApplyOverflowRestrictionsStep(mockRestrictionManager, overflowTopic, false)

        const headers = { token: 'overflow-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ headers })

        expect(isRedirectResult(result)).toBe(true)
        expect(result).toEqual(redirect('overflow_forced', overflowTopic, false, false))
        expect(mockRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('overflow-token', 'user-123')
        expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).toHaveBeenCalledWith(1)
    })

    it('should return ok when consuming from overflow topic even if shouldForceOverflow is true', async () => {
        mockRestrictionManager.shouldForceOverflow.mockReturnValue(true)
        const step = createApplyOverflowRestrictionsStep(mockRestrictionManager, overflowTopic, true)

        const headers = { token: 'overflow-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ headers })

        expect(isOkResult(result)).toBe(true)
        expect(mockRestrictionManager.shouldForceOverflow).not.toHaveBeenCalled()
        expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).not.toHaveBeenCalled()
    })

    it('should handle undefined token', async () => {
        mockRestrictionManager.shouldForceOverflow.mockReturnValue(false)
        const step = createApplyOverflowRestrictionsStep(mockRestrictionManager, overflowTopic, false)

        const headers = { distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ headers })

        expect(isOkResult(result)).toBe(true)
        expect(mockRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(undefined, 'user-123')
    })

    it('should handle undefined distinct_id', async () => {
        mockRestrictionManager.shouldForceOverflow.mockReturnValue(false)
        const step = createApplyOverflowRestrictionsStep(mockRestrictionManager, overflowTopic, false)

        const headers = { token: 'test-token', force_disable_person_processing: false }

        const result = await step({ headers })

        expect(isOkResult(result)).toBe(true)
        expect(mockRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('test-token', undefined)
    })

    it('should return message unchanged when ok', async () => {
        mockRestrictionManager.shouldForceOverflow.mockReturnValue(false)
        const step = createApplyOverflowRestrictionsStep(mockRestrictionManager, overflowTopic, false)

        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }

        const result = await step({ headers })

        expect(isOkResult(result)).toBe(true)
        expect(result).toEqual(ok({ headers }))
    })

    it('should preserve generic input properties not specified in Input type', async () => {
        mockRestrictionManager.shouldForceOverflow.mockReturnValue(false)
        const step = createApplyOverflowRestrictionsStep<{
            headers: EventHeaders
            customField: string
            anotherField: number
        }>(mockRestrictionManager, overflowTopic, false)

        const headers = { token: 'test-token', distinct_id: 'user-123', force_disable_person_processing: false }
        const input = { headers, customField: 'test-value', anotherField: 123 }

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value).toMatchObject({
                headers,
                customField: 'test-value',
                anotherField: 123,
            })
        }
    })
})
