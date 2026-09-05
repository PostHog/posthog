import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
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
    description: 'First line\nSecond line\nThird line',
    status: 'open',
    assigned_to: { id: 7, email: 'casey@example.com', first_name: 'Casey', last_name: 'Kim' },
    due_at: null,
    completed_at: null,
    completed_by: null,
    created_by: null,
    archived_at: null,
    created_at: '2026-09-02T10:00:00Z',
    updated_at: '2026-09-02T10:00:00Z',
    can_edit: false,
    can_restore: false,
}

function tableHeaders(table: HTMLElement): HTMLTableCellElement[] {
    return Array.from(table.querySelectorAll('thead th'))
}

function findTableHeader(table: HTMLElement, title: string): HTMLTableCellElement | undefined {
    return tableHeaders(table).find((header) => header.textContent?.trim() === title)
}

function filterBar(container: HTMLElement): HTMLElement {
    return container.querySelector('[data-attr="customer-tasks-filters"]') as HTMLElement
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

    test('renders task details and opens the read-only modal', async () => {
        await expectLogic(logic).toFinishAllListeners()

        render(
            <Provider>
                <CustomerTasksTable logic={logic} context="inbox" />
            </Provider>
        )

        const table = screen.getByRole('table')
        expect(tableHeaders(table)[0]).toHaveTextContent('Task')
        const taskName = within(table).getByText('Follow up')
        const taskRow = taskName.closest('tr')
        expect(taskRow).not.toBeNull()
        expect(within(taskRow!).getByText('First line Second line Third line')).toBeInTheDocument()
        // The member list loads only once a picker opens, so the row has to name the assignee itself.
        expect(taskRow!.querySelector('[data-attr="customer-task-assignee"]')).toHaveTextContent('Casey Kim')

        fireEvent.click(taskName)
        const dialog = screen.getByRole('dialog')
        expect(within(dialog).getByText('Task details')).toBeInTheDocument()
        expect(within(dialog).getByText('Account (optional)')).toBeInTheDocument()
        expect(within(dialog).getByDisplayValue('No account')).toBeDisabled()
        expect(within(dialog).getByDisplayValue('Follow up')).toBeDisabled()
        expect(within(dialog).queryByText('Save changes')).not.toBeInTheDocument()
        expect(within(dialog).getByText('Close')).toBeInTheDocument()

        mockList.mockResolvedValueOnce({
            count: 1,
            next: null,
            previous: null,
            results: [{ ...accountlessTask, description: ' ' }],
        })
        logic.actions.loadTaskPage()
        await expectLogic(logic).toFinishAllListeners()
        expect(within(table).queryByText('First line Second line Third line')).not.toBeInTheDocument()
    })

    test('shows the task assignee before project members load', async () => {
        mockList.mockResolvedValueOnce({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    ...accountlessTask,
                    assigned_to: {
                        id: 178,
                        email: 'alex@example.com',
                        first_name: 'Alex',
                        last_name: 'Morgan',
                    },
                },
            ],
        })
        await expectLogic(logic).toFinishAllListeners()

        render(
            <Provider>
                <CustomerTasksTable logic={logic} context="inbox" />
            </Provider>
        )

        expect(screen.getAllByText('Alex Morgan').length).toBeGreaterThan(0)
        fireEvent.click(screen.getByText('Follow up'))
        expect(within(screen.getByRole('dialog')).getByText('Alex Morgan')).toBeInTheDocument()
    })

    test.each([
        ['Task', 'name'],
        ['Status', 'status'],
        ['Assignee', 'assigned_to'],
        ['Due', '-due_at'],
        ['Updated', 'updated_at'],
        ['Account', 'account'],
    ])('orders by %s on the server and resets pagination', async (header, ordering) => {
        await expectLogic(logic).toFinishAllListeners()
        render(
            <Provider>
                <CustomerTasksTable logic={logic} context="inbox" />
            </Provider>
        )
        const table = screen.getByRole('table')

        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockClear()

        const tableHeader = findTableHeader(table, header)
        if (!tableHeader) {
            throw new Error(`Missing ${header} table header`)
        }
        fireEvent.click(within(tableHeader).getByText(header))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ ordering, offset: 0 }))
    })

    test('shows Account ordering and assignee filters only in the inbox', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const inbox = render(
            <Provider>
                <CustomerTasksTable logic={logic} context="inbox" canViewAll />
            </Provider>
        )
        expect(findTableHeader(screen.getByRole('table'), 'Account')).not.toBeUndefined()
        expect(within(filterBar(inbox.container)).queryByText('Choose member')).not.toBeNull()

        cleanup()
        logic.unmount()
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const accountTable = render(
            <Provider>
                <CustomerTasksTable logic={logic} context="account" canViewAll />
            </Provider>
        )

        expect(findTableHeader(accountTable.getByRole('table'), 'Account')).toBeUndefined()
        expect(within(filterBar(accountTable.container)).queryByText('Choose member')).toBeNull()
    })
})
