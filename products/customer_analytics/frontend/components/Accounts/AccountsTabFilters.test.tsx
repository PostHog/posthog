import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { dataNodeLogic } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
        logic = accountsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
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

    // Regression: the role pickers used to resolve the selected member's name from the
    // lazily-loaded org members list, so a filter restored from the URL showed "Any CSM"
    // until the dropdown was opened — the list was filtered but the control looked empty.
    it('reflects a restored role filter without the members list being loaded', () => {
        logic.actions.setCsmFilter([42])
        renderFilters()

        expect(screen.getByText('1 CSM')).toBeInTheDocument()
        expect(screen.queryByText('Any CSM')).not.toBeInTheDocument()
    })

    it('summarizes multiple selected members as a count', () => {
        logic.actions.setAccountExecutiveFilter([1, 2, 3])
        renderFilters()

        expect(screen.getByText('3 AEs')).toBeInTheDocument()
    })

    it('shows the default label when no role is selected', () => {
        renderFilters()

        expect(screen.getByText('Any Owner')).toBeInTheDocument()
    })
})
