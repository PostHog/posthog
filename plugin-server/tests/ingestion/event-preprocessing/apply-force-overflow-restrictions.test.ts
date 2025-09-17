import {
    OverflowConfig,
    createApplyForceOverflowRestrictionsStep,
} from '../../../src/ingestion/event-preprocessing/apply-force-overflow-restrictions'
import { EventHeaders } from '../../../src/types'
import { EventIngestionRestrictionManager } from '../../../src/utils/event-ingestion-restriction-manager'
import { redirect, success } from '../../../src/worker/ingestion/event-pipeline/pipeline-step-result'

describe('createApplyForceOverflowRestrictionsStep', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager
    let overflowConfig: OverflowConfig
    let step: ReturnType<typeof createApplyForceOverflowRestrictionsStep>

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            shouldForceOverflow: jest.fn(),
            shouldSkipPerson: jest.fn(),
        } as unknown as EventIngestionRestrictionManager

        overflowConfig = {
            overflowTopic: 'overflow-topic',
            preservePartitionLocality: true,
            overflowEnabled: true,
        }

        step = createApplyForceOverflowRestrictionsStep(eventIngestionRestrictionManager, overflowConfig)
    })

    it('returns success when not forcing overflow', () => {
        const input = {
            message: {} as any,
            headers: {
                token: 'valid-token-123',
                distinct_id: 'user-456',
            },
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = step(input)

        expect(result).toEqual(success(input))
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('valid-token-123', 'user-456')
        // shouldSkipPerson should not be called if not forcing overflow
        expect(eventIngestionRestrictionManager.shouldSkipPerson).not.toHaveBeenCalled()
    })

    it('redirects with preserved partition locality when not skipping person', () => {
        const input = {
            message: {} as any,
            headers: {
                token: 't-xyz',
                distinct_id: 'd-1',
            },
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = step(input)

        expect(result).toEqual(
            redirect('Event redirected to overflow due to force overflow restrictions', 'overflow-topic', true, false)
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('t-xyz', 'd-1')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith('t-xyz', 'd-1')
    })

    it('redirects without preserving partition locality when skipping person', () => {
        const input = {
            message: {} as any,
            headers: {
                token: 't-abc',
                distinct_id: 'd-2',
            },
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = step(input)

        expect(result).toEqual(
            redirect(
                'Event redirected to overflow due to force overflow restrictions',
                'overflow-topic',
                true, // Uses overflowConfig.preservePartitionLocality when undefined
                false
            )
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith('t-abc', 'd-2')
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith('t-abc', 'd-2')
    })

    it('handles undefined headers', () => {
        const input = {
            message: {} as any,
            headers: {} as EventHeaders,
        }
        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = step(input)

        expect(result).toEqual(success(input))
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(undefined, undefined)
    })

    it('handles empty headers', () => {
        const input = {
            message: {} as any,
            headers: {},
        }
        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = step(input)

        expect(result).toEqual(success(input))
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(undefined, undefined)
    })

    it('returns success when overflow is disabled', () => {
        const disabledOverflowConfig: OverflowConfig = {
            ...overflowConfig,
            overflowEnabled: false,
        }
        const disabledStep = createApplyForceOverflowRestrictionsStep(
            eventIngestionRestrictionManager,
            disabledOverflowConfig
        )

        const input = {
            message: {} as any,
            headers: {
                token: 'test-token',
                distinct_id: 'test-user',
            },
        }

        const result = disabledStep(input)

        expect(result).toEqual(success(input))
        expect(eventIngestionRestrictionManager.shouldForceOverflow).not.toHaveBeenCalled()
        expect(eventIngestionRestrictionManager.shouldSkipPerson).not.toHaveBeenCalled()
    })
})
