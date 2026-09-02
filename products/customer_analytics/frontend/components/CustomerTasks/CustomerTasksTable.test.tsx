import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { accountsList, customerTasksList } from 'products/customer_analytics/frontend/generated/api'
import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerTasksLogic } from './customerTasksLogic'
import { CustomerTasksTable } from './CustomerTasksTable'

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

const accountlessTask: CustomerTaskApi = {
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
    can_edit: false,
}

describe('CustomerTasksTable', () => {
    let logic: ReturnType<typeof customerTasksLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockList.mockResolvedValue({ count: 1, next: null, previous: null, results: [accountlessTask] })
        mockAccounts.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        logic = customerTasksLogic({ context: 'inbox' })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('shows accountless tasks in the personal inbox', async () => {
        await expectLogic(logic).toFinishAllListeners()

        render(
            <Provider>
                <CustomerTasksTable logic={logic} context="inbox" />
            </Provider>
        )

        expect(screen.getByText('No account')).toBeInTheDocument()
    })
})
