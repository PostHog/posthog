import {
    customerTaskDueBounds,
    customerTasksQuery,
    defaultCustomerTaskFilters,
    hasCustomerTaskFilters,
} from './customerTaskFilters'
import type { CustomerTaskDueFilter, CustomerTasksContext } from './customerTaskFilters'

describe('customer task filter helpers', () => {
    test.each([
        [
            'account',
            20,
            {
                account_id: 'account-1',
                statuses: 'open,in_progress',
                archive_state: 'active',
                ordering: 'due_at',
                limit: 20,
                offset: 0,
            },
        ],
        [
            'inbox',
            50,
            {
                assigned_to: 'me',
                statuses: 'open,in_progress',
                archive_state: 'active',
                ordering: 'due_at',
                limit: 50,
                offset: 0,
            },
        ],
    ])('builds the documented %s defaults', (context, pageSize, expected) => {
        const accountId = context === 'account' ? 'account-1' : undefined
        expect(
            customerTasksQuery(
                defaultCustomerTaskFilters(context as CustomerTasksContext),
                context as CustomerTasksContext,
                accountId,
                1,
                pageSize,
                'UTC'
            )
        ).toEqual(expected)
    })

    test('resets the active state to the context defaults', () => {
        const filters = { ...defaultCustomerTaskFilters('inbox'), search: 'follow up', status: 'completed' as const }
        expect(hasCustomerTaskFilters(filters, 'inbox')).toBe(true)
        expect(hasCustomerTaskFilters(defaultCustomerTaskFilters('inbox'), 'inbox')).toBe(false)
    })

    test.each([
        ['overdue', { due_before: '2026-09-02T10:00:00.000Z' }],
        ['upcoming', { due_after: '2026-09-02T10:00:00.000Z' }],
        ['no_due_date', { has_due_at: false }],
    ])('translates the %s due filter', (due, expected) => {
        expect(customerTaskDueBounds(due as CustomerTaskDueFilter, 'UTC', '2026-09-02T10:00:00.000Z')).toEqual(expected)
    })

    test('uses project timezone boundaries for Today', () => {
        expect(customerTaskDueBounds('today', 'America/Los_Angeles', '2026-09-02T10:00:00.000Z')).toEqual({
            due_after: '2026-09-02T07:00:00.000Z',
            due_before: '2026-09-03T07:00:00.000Z',
        })
    })
})
