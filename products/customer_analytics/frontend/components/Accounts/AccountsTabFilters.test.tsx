import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { ACCOUNTS_HOGQL_DATA_NODE_KEY } from '../../constants'
import { accountsLogic } from './accountsLogic'
import { AccountsTabFilters } from './AccountsTabFilters'

describe('AccountsTabFilters', () => {
    let logic: ReturnType<typeof accountsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/members/': () => [200, { results: [] }],
                '/api/projects/:team_id/tags': () => [200, []],
                '/api/environments/:team_id/column_configurations': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        // The shared "my accounts" (mineOnly) toggle persists to localStorage; clear it so a
        // value set by one test can't bleed into the next (which would pre-check the checkbox).
        localStorage.clear()
        logic = accountsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
        localStorage.clear()
    })

    function renderFilters(): void {
        render(
            <Provider>
                <BindLogic
                    logic={dataNodeLogic}
                    props={{ key: ACCOUNTS_HOGQL_DATA_NODE_KEY, query: {}, autoLoad: false }}
                >
                    <AccountsTabFilters />
                </BindLogic>
            </Provider>
        )
    }

    function myAccountsCheckbox(): HTMLInputElement {
        return screen.getByText('My accounts').closest('.LemonCheckbox')!.querySelector('input')!
    }

    it('renders the "My accounts" checkbox', () => {
        renderFilters()

        expect(screen.getByText('My accounts')).toBeInTheDocument()
        expect(myAccountsCheckbox().checked).toBe(false)
    })

    it('reflects a restored my-accounts filter as checked', () => {
        userLogic.actions.loadUserSuccess({ id: 42 } as unknown as UserType)
        logic.actions.setAssignedToCurrentUser(true)
        renderFilters()

        expect(myAccountsCheckbox().checked).toBe(true)
    })

    it('clicking it enables the my-accounts filter (resolved to the current user id)', () => {
        userLogic.actions.loadUserSuccess({ id: 42 } as unknown as UserType)
        renderFilters()

        fireEvent.click(myAccountsCheckbox())

        expect(logic.values.assignedToFilter).toEqual([42])
        expect(logic.values.assignedToCurrentUser).toBe(true)
    })

    it('renders the "Assigned to" picker with its default label', () => {
        renderFilters()

        expect(screen.getByText('Assigned to anyone')).toBeInTheDocument()
    })

    // Regression: the picker must summarize a URL-restored filter from the id count
    // alone, without waiting on the lazily-loaded org members list — otherwise the
    // control looks empty (the default label) until the dropdown is opened.
    it('reflects a restored assigned-to filter as a count', () => {
        logic.actions.setAssignedToFilter([1, 2])
        renderFilters()

        expect(screen.getByText('Assigned to 2 people')).toBeInTheDocument()
        expect(screen.queryByText('Assigned to anyone')).not.toBeInTheDocument()
    })

    it('labels the assigned-to picker "Unassigned" when unassigned-only is active', () => {
        logic.actions.setAllRolesUnassigned(true)
        renderFilters()

        expect(screen.getByText('Unassigned')).toBeInTheDocument()
        expect(screen.queryByText('Assigned to anyone')).not.toBeInTheDocument()
    })
})
