import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { calendarSyncBackfillCreate, calendarSyncList } from 'products/customer_analytics/frontend/generated/api'

import { calendarSyncLogic, getGoogleAccountBackfillDateError } from './calendarSyncLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    calendarSyncBackfillCreate: jest.fn(),
    calendarSyncList: jest.fn(),
}))

const mockBackfill = calendarSyncBackfillCreate as jest.MockedFunction<typeof calendarSyncBackfillCreate>
const mockList = calendarSyncList as jest.MockedFunction<typeof calendarSyncList>

describe('calendarSyncLogic', () => {
    let logic: ReturnType<typeof calendarSyncLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockList.mockResolvedValue([])
        logic = calendarSyncLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('opens a backfill with the last 90 UTC dates selected', () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-04-10T12:00:00Z'))

        logic.actions.openBackfill(7)

        expect(logic.values.backfillIntegrationId).toBe(7)
        expect(logic.values.backfillStartDate).toBe('2026-01-11')
        expect(logic.values.backfillEndDate).toBe('2026-04-10')
        expect(logic.values.backfillDateError).toBeNull()
    })

    test.each([
        [null, '2026-04-10', 'Select a start date and an end date.'],
        ['2025-04-09', '2026-04-10', 'The start date must be within the last year.'],
        ['2026-04-10', '2026-04-11', 'The end date cannot be after today.'],
        ['2026-04-10', '2026-04-09', 'The end date must be on or after the start date.'],
    ])('validates a bounded date range', (startDate, endDate, expectedError) => {
        expect(getGoogleAccountBackfillDateError(startDate, endDate, '2026-04-10')).toBe(expectedError)
    })

    it('keeps a newly opened modal when an earlier request finishes', async () => {
        let resolveBackfill: ((value: { status: 'started' }) => void) | undefined
        mockBackfill.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveBackfill = resolve
                })
        )
        logic.actions.openBackfill(7)
        logic.actions.submitBackfill(7, '2026-01-11', '2026-04-10')
        await Promise.resolve()
        logic.actions.closeBackfill()
        logic.actions.openBackfill(8)

        const completed = expectLogic(logic).toDispatchActions(['backfillFinished'])
        resolveBackfill?.({ status: 'started' })
        await completed

        expect(logic.values.backfillIntegrationId).toBe(8)
    })

    it('submits the selected range and closes the modal', async () => {
        mockBackfill.mockResolvedValue({ status: 'started' })
        logic.actions.openBackfill(7)

        await expectLogic(logic, () => logic.actions.submitBackfill(7, '2026-01-11', '2026-04-10')).toDispatchActions([
            'closeBackfill',
            'backfillFinished',
        ])

        expect(mockBackfill).toHaveBeenCalledWith(expect.any(String), {
            integration_id: 7,
            start_date: '2026-01-11',
            end_date: '2026-04-10',
        })
        expect(logic.values.backfillIntegrationId).toBeNull()
        expect(logic.values.backfillSubmitting).toBe(false)
    })
})
