import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { ok, redirect } from '../pipelines/results'
import { OverflowConfig, createApplyForceOverflowRestrictionsStep } from './apply-force-overflow-restrictions'

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

    it('returns success when not forcing overflow', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 'valid-token-123',
                distinct_id: 'user-456',
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            'valid-token-123',
            'user-456',
            undefined,
            undefined,
            undefined
        )
        // shouldSkipPerson should not be called if not forcing overflow
        expect(eventIngestionRestrictionManager.shouldSkipPerson).not.toHaveBeenCalled()
    })

    it('redirects with preserved partition locality when not skipping person', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 't-xyz',
                distinct_id: 'd-1',
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(
            redirect('Event redirected to overflow due to force overflow restrictions', 'overflow-topic', true, false)
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            't-xyz',
            'd-1',
            undefined,
            undefined,
            undefined
        )
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            't-xyz',
            'd-1',
            undefined,
            undefined,
            undefined
        )
    })

    it('redirects without preserving partition locality when skipping person', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 't-abc',
                distinct_id: 'd-2',
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(
            redirect(
                'Event redirected to overflow due to force overflow restrictions',
                'overflow-topic',
                true, // Uses overflowConfig.preservePartitionLocality when undefined
                false
            )
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            't-abc',
            'd-2',
            undefined,
            undefined,
            undefined
        )
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            't-abc',
            'd-2',
            undefined,
            undefined,
            undefined
        )
    })

    it('handles undefined headers', async () => {
        const input = {
            message: {} as any,
            headers: {} as EventHeaders,
        }
        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            undefined,
            undefined,
            undefined,
            undefined,
            undefined
        )
    })

    it('handles empty headers', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders(),
        }
        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            undefined,
            undefined,
            undefined,
            undefined,
            undefined
        )
    })

    it('passes session_id to restriction checks when present', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 't-xyz',
                distinct_id: 'd-1',
                session_id: 's-123',
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(
            redirect('Event redirected to overflow due to force overflow restrictions', 'overflow-topic', true, false)
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            't-xyz',
            'd-1',
            's-123',
            undefined,
            undefined
        )
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            't-xyz',
            'd-1',
            's-123',
            undefined,
            undefined
        )
    })

    it('overflows event when session_id is restricted', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 't-abc',
                distinct_id: 'd-2',
                session_id: 'blocked-session',
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(
            redirect('Event redirected to overflow due to force overflow restrictions', 'overflow-topic', true, false)
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            't-abc',
            'd-2',
            'blocked-session',
            undefined,
            undefined
        )
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            't-abc',
            'd-2',
            'blocked-session',
            undefined,
            undefined
        )
    })

    it('passes event name to restriction checks when present', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 't-xyz',
                distinct_id: 'd-1',
                event: '$pageview',
                force_disable_person_processing: false,
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(
            redirect('Event redirected to overflow due to force overflow restrictions', 'overflow-topic', true, false)
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            't-xyz',
            'd-1',
            undefined,
            '$pageview',
            undefined
        )
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            't-xyz',
            'd-1',
            undefined,
            '$pageview',
            undefined
        )
    })

    it('passes uuid to restriction checks when present', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 't-xyz',
                distinct_id: 'd-1',
                uuid: 'event-uuid-123',
                force_disable_person_processing: false,
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

        const result = await step(input)

        expect(result).toEqual(
            redirect('Event redirected to overflow due to force overflow restrictions', 'overflow-topic', true, false)
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            't-xyz',
            'd-1',
            undefined,
            undefined,
            'event-uuid-123'
        )
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            't-xyz',
            'd-1',
            undefined,
            undefined,
            'event-uuid-123'
        )
    })

    it('overflows event when event_name is restricted', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 't-abc',
                distinct_id: 'd-2',
                event: '$blocked_event',
                force_disable_person_processing: false,
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(
            redirect('Event redirected to overflow due to force overflow restrictions', 'overflow-topic', true, false)
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            't-abc',
            'd-2',
            undefined,
            '$blocked_event',
            undefined
        )
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            't-abc',
            'd-2',
            undefined,
            '$blocked_event',
            undefined
        )
    })

    it('overflows event when uuid is restricted', async () => {
        const input = {
            message: {} as any,
            headers: createTestEventHeaders({
                token: 't-abc',
                distinct_id: 'd-2',
                uuid: 'blocked-uuid-789',
                force_disable_person_processing: false,
            }),
        }

        jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
        jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

        const result = await step(input)

        expect(result).toEqual(
            redirect('Event redirected to overflow due to force overflow restrictions', 'overflow-topic', true, false)
        )
        expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
            't-abc',
            'd-2',
            undefined,
            undefined,
            'blocked-uuid-789'
        )
        expect(eventIngestionRestrictionManager.shouldSkipPerson).toHaveBeenCalledWith(
            't-abc',
            'd-2',
            undefined,
            undefined,
            'blocked-uuid-789'
        )
    })

    it('returns success when overflow is disabled', async () => {
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
            headers: createTestEventHeaders({
                token: 'test-token',
                distinct_id: 'test-user',
            }),
        }

        const result = await disabledStep(input)

        expect(result).toEqual(ok(input))
        expect(eventIngestionRestrictionManager.shouldForceOverflow).not.toHaveBeenCalled()
        expect(eventIngestionRestrictionManager.shouldSkipPerson).not.toHaveBeenCalled()
    })
})
