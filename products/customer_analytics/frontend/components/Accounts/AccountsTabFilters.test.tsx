import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator, type UserType } from '~/types'

import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_TABLE_DATA_NODE_KEY } from '../../constants'
import { accountsLogic } from './accountsLogic'
import { AccountsTabFilters } from './AccountsTabFilters'
import { accountsViewsLogic } from './accountsViewsLogic'
import { accountsViewIdStorageKey } from './accountsViewState'

describe('AccountsTabFilters', () => {
    let logic: ReturnType<typeof accountsLogic.build>
    let savedViews: ColumnConfigurationApi[]
    let tagsRequest: jest.Mock
    let viewsRequest: jest.Mock
    let manualViewsLogic: ReturnType<typeof accountsViewsLogic.build> | null

    beforeEach(() => {
        manualViewsLogic = null
        savedViews = []
        tagsRequest = jest.fn(() => [200, ['enterprise']])
        viewsRequest = jest.fn(() => [200, { count: savedViews.length, results: savedViews }])
        useMocks({
            get: {
                '/api/organizations/:organization_id/members/': () => [200, { results: [] }],
                '/api/projects/:team_id/tags': tagsRequest,
                '/api/projects/:team_id/column_configurations': viewsRequest,
            },
        })
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            current_team: MOCK_DEFAULT_TEAM,
            current_user: MOCK_DEFAULT_USER,
        } as any
        initKeaTests()
        localStorage.clear()
        logic = accountsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
        manualViewsLogic?.unmount()
        localStorage.clear()
    })

    function renderFilters(): void {
        render(
            <Provider>
                <BindLogic
                    logic={dataNodeLogic}
                    props={{ key: ACCOUNTS_TABLE_DATA_NODE_KEY, query: {}, autoLoad: false }}
                >
                    <AccountsTabFilters />
                </BindLogic>
            </Provider>
        )
    }

    function myAccountsCheckbox(): HTMLInputElement {
        return screen.getByText('My accounts').closest('.LemonCheckbox')!.querySelector('input')!
    }

    it('offers edit and delete for a shared saved view', async () => {
        savedViews = [
            {
                id: 'shared-view',
                context_key: 'customer_analytics_accounts_columns',
                columns: ['name'],
                name: 'Shared accounts',
                filters: {},
                order_by: [],
                properties: {},
                visibility: 'shared',
                created_by: 999,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
            },
        ]
        renderFilters()

        fireEvent.click(await screen.findByText('Select view'))

        const sharedViewLabel = await screen.findByText('Shared accounts')
        const viewMenuItem = sharedViewLabel.closest('li')
        expect(viewMenuItem).not.toBeNull()

        const viewButtons = viewMenuItem!.querySelectorAll('button')
        expect(viewButtons).toHaveLength(2)
        fireEvent.click(viewButtons[1])

        expect(await screen.findByText('Edit')).toBeInTheDocument()
        expect(screen.getByText('Delete')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Edit'))
        expect(await screen.findByText('Edit view')).toBeInTheDocument()
        expect(screen.getByDisplayValue('Shared accounts')).toBeInTheDocument()
    })

    it.each([true, false])(
        'renders the cached picker immediately and hydrates without showing Save current view (exists=%s)',
        async (exists) => {
            const view: ColumnConfigurationApi = {
                id: 'cached-view',
                context_key: 'customer_analytics_accounts_columns',
                columns: ['name'],
                name: 'Cached accounts',
                filters: { assignmentStatus: 'all' },
                order_by: [],
                properties: {},
                visibility: 'shared',
                created_by: MOCK_DEFAULT_USER.id,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
            }
            savedViews = exists ? [view] : [{ ...view, id: 'other-view', name: 'Other view' }]
            localStorage.setItem(
                accountsViewIdStorageKey(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid),
                JSON.stringify({ id: view.id, name: view.name })
            )
            let release!: () => void
            const pending = new Promise<void>((resolve) => {
                release = resolve
            })
            viewsRequest.mockImplementationOnce(async () => {
                await pending
                return [200, { count: savedViews.length, results: savedViews }]
            })
            renderFilters()
            const initialSelector = screen.getByText('Cached accounts').closest('button')
            expect(initialSelector).toBeInTheDocument()
            expect(screen.queryByText('Save current view')).not.toBeInTheDocument()

            await act(async () => release())
            await waitFor(() => expect(accountsViewsLogic.values.viewsLoaded).toBe(true))
            expect(screen.getByText(exists ? 'Cached accounts' : 'Select view').closest('button')).toBe(initialSelector)
            expect(screen.queryByText('Save current view')).not.toBeInTheDocument()
            expect(document.querySelector('[data-attr="accounts-update-view"]')).toBeNull()
        }
    )

    it('loads existing tags when the tag filter opens', async () => {
        renderFilters()

        fireEvent.click(screen.getByText('All tags'))
        await waitFor(() => expect(tagsRequest).toHaveBeenCalled())
        fireEvent.focus(screen.getByPlaceholderText('Select or type tags...'))

        expect(await screen.findByText('enterprise')).toBeInTheDocument()
    })

    it('renders the "My accounts" checkbox', () => {
        renderFilters()

        expect(screen.getByText('My accounts')).toBeInTheDocument()
        expect(myAccountsCheckbox().checked).toBe(false)
    })

    it('reflects a restored my-accounts filter as checked', () => {
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, id: 42 } as unknown as UserType)
        logic.actions.setAssignedToCurrentUser(true)
        renderFilters()

        expect(myAccountsCheckbox().checked).toBe(true)
    })

    it('clicking My accounts filters to the current user and removing it restores all assignment statuses', () => {
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, id: 42 } as unknown as UserType)
        renderFilters()
        fireEvent.click(myAccountsCheckbox())
        expect(logic.values.assignedToFilter).toEqual([42])
        expect(logic.values.assignedToCurrentUser).toBe(true)

        fireEvent.click(myAccountsCheckbox())
        expect(myAccountsCheckbox().checked).toBe(false)
        expect(logic.values.assignedToFilter).toEqual([])
        expect(logic.values.assignmentStatus).toBe('all')
        expect(screen.getByText('All accounts')).toBeInTheDocument()
    })

    it('renders the "Assigned to" picker with its default label', () => {
        renderFilters()

        // Default shows every account regardless of assignment.
        expect(screen.getByText('All accounts')).toBeInTheDocument()
    })

    it('updates the Accounts assignment status from the shared picker', () => {
        renderFilters()

        fireEvent.click(screen.getByText('All accounts'))
        fireEvent.click(screen.getByText('Assigned to anyone'))

        expect(logic.values.assignmentStatus).toBe('assigned')
    })
    it('keeps OR branches when collapsed and returns to the empty trigger after removing every group', async () => {
        manualViewsLogic = accountsViewsLogic()
        manualViewsLogic.mount()
        await waitFor(() => expect(manualViewsLogic!.values.viewsLoaded).toBe(true))
        const first = [
            {
                type: PropertyFilterType.Account as const,
                key: 'name',
                operator: PropertyOperator.Exact,
                value: ['Acme'],
            },
        ]
        const second = [
            {
                type: PropertyFilterType.Account as const,
                key: 'name',
                operator: PropertyOperator.Exact,
                value: ['Globex'],
            },
        ]
        logic.actions.setAccountFilters(first)
        logic.actions.setAccountFilterGroups([second])
        renderFilters()

        expect(screen.queryByText('Add OR group')).not.toBeInTheDocument()
        expect(screen.getByText('Filters').closest('button')).toHaveAttribute('aria-expanded', 'false')
        fireEvent.click(screen.getByText('Filters'))
        expect(screen.getByText('Filters').closest('button')).toHaveAttribute('aria-expanded', 'true')
        expect(screen.queryByText('Match all conditions')).not.toBeInTheDocument()
        expect(await screen.findByText('Add OR group')).toBeInTheDocument()
        fireEvent.click(screen.getByText('Filters'))
        expect(logic.values.accountFilters).toEqual(first)
        expect(logic.values.accountFilterGroups).toEqual([second])

        fireEvent.click(screen.getByText('Filters'))
        fireEvent.click(await screen.findByLabelText('Remove group A'))
        expect(logic.values.accountFilters).toEqual(second)
        expect(logic.values.accountFilterGroups).toEqual([])
        fireEvent.click(screen.getByLabelText('Remove group A'))
        expect(await screen.findByText('Filter')).toBeInTheDocument()
        expect(screen.queryByText('Filters')).not.toBeInTheDocument()
        expect(logic.values.accountFilters).toEqual([])
    })
})
