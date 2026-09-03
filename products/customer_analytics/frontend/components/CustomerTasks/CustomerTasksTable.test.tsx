import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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

function tableHeaders(container: HTMLElement): HTMLTableCellElement[] {
    return Array.from(container.querySelectorAll('thead th'))
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

    test('renders Task first with a linked, two-line description preview', async () => {
        await expectLogic(logic).toFinishAllListeners()

        const { container } = render(
            <Provider>
                <CustomerTasksTable logic={logic} context="inbox" />
            </Provider>
        )

        expect(tableHeaders(container)[0].textContent).toContain('Task')
        expect(tableHeaders(container).at(-1)).not.toHaveClass('LemonTable__header--actionable')
        const taskName = screen.getByText('Follow up')
        expect(taskName).toHaveClass('Link', 'Link--subtle', 'font-semibold')
        expect(taskName).not.toHaveClass('LemonButton')
        const descriptionPreview = container.querySelector('tbody .line-clamp-2')
        expect(descriptionPreview).toHaveTextContent('First line Second line Third line')
        expect(descriptionPreview).toHaveClass('text-muted', 'line-clamp-2')

        fireEvent.click(taskName)
        expect(screen.getByText('Edit task')).toBeInTheDocument()
        expect(screen.getByText('Account (optional)')).toBeInTheDocument()
        expect(screen.getByText('No account')).toBeInTheDocument()

        mockList.mockResolvedValueOnce({
            count: 1,
            next: null,
            previous: null,
            results: [{ ...accountlessTask, description: ' ' }],
        })
        logic.actions.loadTaskPage()
        await expectLogic(logic).toFinishAllListeners()
        expect(container.querySelector('tbody .line-clamp-2')).not.toBeInTheDocument()
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
        const { container } = render(
            <Provider>
                <CustomerTasksTable logic={logic} context="inbox" />
            </Provider>
        )

        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockClear()

        const tableHeader = tableHeaders(container).find((element) => element.textContent?.includes(header))
        if (!tableHeader) {
            throw new Error(`Missing ${header} table header`)
        }
        const tableHeaderContent = tableHeader.querySelector('.LemonTable__header-content')
        if (!tableHeaderContent) {
            throw new Error(`Missing ${header} table header content`)
        }
        fireEvent.click(tableHeaderContent)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ ordering, offset: 0 }))
    })

    test('shows Account ordering only in the inbox', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const { container } = render(
            <Provider>
                <CustomerTasksTable logic={logic} context="inbox" />
            </Provider>
        )
        expect(tableHeaders(container).some((element) => element.textContent?.includes('Account'))).toBe(true)

        cleanup()
        logic.unmount()
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const accountTable = render(
            <Provider>
                <CustomerTasksTable logic={logic} context="account" />
            </Provider>
        )

        expect(tableHeaders(accountTable.container).some((element) => element.textContent?.includes('Account'))).toBe(
            false
        )
    })
})
