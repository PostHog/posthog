import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    customerTaskDueBounds,
    customerTaskEditDisabledReason,
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

    test('keeps an assignee and omits due filters in account context', () => {
        const query = customerTasksQuery(
            { ...defaultCustomerTaskFilters('account'), assignee: 42, due: 'overdue' },
            'account',
            'account-1',
            1,
            20,
            'UTC'
        )

        expect(query).toMatchObject({ account_id: 'account-1', assigned_to: '42' })
        expect(query).not.toHaveProperty('due_after')
        expect(query).not.toHaveProperty('due_before')
        expect(query).not.toHaveProperty('has_due_at')
    })

    test.each([
        ['an archived task', { archived_at: '2026-09-02T11:00:00Z' }, 'Restore this task to edit it'],
        ['a task the user cannot edit', { can_edit: false }, 'You cannot edit this task'],
        ['an editable task', {}, undefined],
    ])('resolves the edit blocker for %s', (_, overrides, expected) => {
        const task = {
            archived_at: null,
            can_edit: true,
            ...(overrides as Partial<CustomerTaskApi>),
        } as CustomerTaskApi
        expect(customerTaskEditDisabledReason(task)).toBe(expected)
    })

    test.each([
        ['a resource viewer', true, 'unassigned'],
        ['an assignment-only user', false, 'me'],
    ])('keeps %s within their allowed assignee scope', (_, canViewAll, assignedTo) => {
        expect(
            customerTasksQuery(
                { ...defaultCustomerTaskFilters('inbox'), assignee: 'unassigned' },
                'inbox',
                undefined,
                1,
                50,
                'UTC',
                canViewAll
            )
        ).toMatchObject({ assigned_to: assignedTo })
    })
})
