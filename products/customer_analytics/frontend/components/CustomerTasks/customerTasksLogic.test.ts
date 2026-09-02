import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    accountsList,
    customerTasksList,
    customerTasksPartialUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerTasksLogic } from './customerTasksLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountsList: jest.fn(),
    customerTasksArchiveCreate: jest.fn(),
    customerTasksCreate: jest.fn(),
    customerTasksList: jest.fn(),
    customerTasksPartialUpdate: jest.fn(),
    customerTasksRestoreCreate: jest.fn(),
}))

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
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockAccounts.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockUpdate.mockResolvedValue(task())
    })

    afterEach(() => logic?.unmount())

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
