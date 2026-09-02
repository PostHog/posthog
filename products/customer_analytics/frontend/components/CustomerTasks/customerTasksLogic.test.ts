import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    accountsList,
    customerTasksCreate,
    customerTasksList,
    customerTasksPartialUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerTasksPersistencePrefix } from './customerTaskFilters'
import { customerTasksLogic } from './customerTasksLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountsList: jest.fn(),
    customerTasksArchiveCreate: jest.fn(),
    customerTasksCreate: jest.fn(),
    customerTasksList: jest.fn(),
    customerTasksPartialUpdate: jest.fn(),
    customerTasksRestoreCreate: jest.fn(),
}))

const mockCreate = customerTasksCreate as jest.MockedFunction<typeof customerTasksCreate>
const mockList = customerTasksList as jest.MockedFunction<typeof customerTasksList>
const mockAccounts = accountsList as jest.MockedFunction<typeof accountsList>
const mockUpdate = customerTasksPartialUpdate as jest.MockedFunction<typeof customerTasksPartialUpdate>

function task(canEdit = true): CustomerTaskApi {
    return {
        id: 'task-1',
        account: null,
        name: 'Follow up',
        description: null,
        status: 'open',
        assigned_to: null,
        due_at: null,
        completed_at: null,
        completed_by: null,
        created_by: null,
        archived_at: null,
        created_at: '2026-09-02T10:00:00Z',
        updated_at: '2026-09-02T10:00:00Z',
        can_edit: canEdit,
    }
}

describe('customerTasksLogic', () => {
    let logic: ReturnType<typeof customerTasksLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        mockCreate.mockResolvedValue(task())
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockAccounts.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockUpdate.mockResolvedValue(task())
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
    })

    test.each([
        ['account', 'account-1', 20, { account_id: 'account-1' }],
        ['inbox', undefined, 50, { assigned_to: 'me' }],
    ])('loads %s with its page size and default filters', async (context, accountId, pageSize, filter) => {
        logic = customerTasksLogic({ context: context as 'account' | 'inbox', accountId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                ...filter,
                statuses: 'open,in_progress',
                archive_state: 'active',
                ordering: 'due_at',
                limit: pageSize,
                offset: 0,
            })
        )
    })

    test('creates a task for the current account without exposing a different account', async () => {
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openCreateModal()
        logic.actions.setDraftName('Follow up')
        logic.actions.submitModal()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockCreate).toHaveBeenCalledWith(expect.any(String), {
            account_id: 'account-1',
            name: 'Follow up',
            description: null,
            assigned_to_id: null,
            due_at: null,
        })
    })

    test('persists inbox filters for one team and user, then resets them to defaults', async () => {
        const prefix = customerTasksPersistencePrefix(1, 42)
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setFilters({ status: 'completed', assignee: 'unassigned' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters).toMatchObject({ status: 'completed', assignee: 'unassigned' })
        logic.unmount()

        const otherUserLogic = customerTasksLogic({
            context: 'inbox',
            canViewAll: true,
            persistPrefix: customerTasksPersistencePrefix(1, 7),
        })
        otherUserLogic.mount()
        await expectLogic(otherUserLogic).toFinishAllListeners()
        expect(otherUserLogic.values.filters).toMatchObject({ status: 'open', assignee: 'me' })
        otherUserLogic.unmount()

        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        expect(logic.values.filters).toMatchObject({ status: 'completed', assignee: 'unassigned' })
        logic.actions.resetFilters()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters).toMatchObject({ status: 'open', assignee: 'me' })
        expect(JSON.stringify(localStorage)).not.toContain('completed')
    })

    test('does not submit a no-op or a mutation for a task the user cannot edit', async () => {
        mockList.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [task()] })
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.updateTask('task-1', { name: 'Follow up' })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockUpdate).not.toHaveBeenCalled()

        mockList.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [task(false)] })
        logic.actions.loadTaskPage()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.updateTask('task-1', { name: 'Changed' })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockUpdate).not.toHaveBeenCalled()
    })
})
