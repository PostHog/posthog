import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AccountsOverviewTilesEditor } from './AccountsOverviewTilesEditor'
import { accountsOverviewTilesLogic, AccountsOverviewTile } from './accountsOverviewTilesLogic'

describe('AccountsOverviewTilesEditor', () => {
    let logic: ReturnType<typeof accountsOverviewTilesLogic.build>

    const thresholdTile: AccountsOverviewTile = {
        id: 'threshold-tile',
        label: 'Accounts > 10',
        metric: {
            type: 'count_threshold',
            columnExpression: 'accounts.custom_properties.values.`00000000-0000-0000-0000-000000000001`',
            columnLabel: 'Health score',
            operator: '>',
            value: 10,
        },
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/column_configurations': () => [200, { count: 0, results: [] }],
                '/api/projects/:team_id/custom_property_definitions': () => [200, { count: 0, results: [] }],
            },
        })
        initKeaTests()
        logic = accountsOverviewTilesLogic()
        logic.mount()
        logic.actions.setTiles([thresholdTile])
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    it('keeps the threshold value when the input is cleared', () => {
        render(
            <Provider>
                <AccountsOverviewTilesEditor isOpen onClose={() => {}} />
            </Provider>
        )

        const input = screen.getByTestId(`accounts-overview-tile-threshold-${thresholdTile.id}`)
        fireEvent.change(input, { target: { value: '' } })

        const metric = logic.values.tiles[0].metric
        expect(metric).toEqual(thresholdTile.metric)
    })
})
