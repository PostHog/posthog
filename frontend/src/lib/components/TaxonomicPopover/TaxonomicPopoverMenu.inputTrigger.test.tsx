import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { __clearTaxonomicResourceCache } from 'lib/components/TaxonomicFilter/hooks/useTaxonomicResource'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { emptyPaginated } from '~/test/mocks/taxonomicFilterApiMock'
import { EntityTypes, FunnelDatawarehouseFilter } from '~/types'

import { TaxonomicPopoverMenu } from './TaxonomicPopoverMenu'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('lib/api', () => require('~/test/mocks/taxonomicFilterApiMock').buildTaxonomicFilterApiMock())

const apiGet = jest.requireMock('lib/api').default.get as jest.MockedFunction<any>

function renderInputTriggerPopoverMenu(): ReturnType<typeof render> {
    return render(
        <Provider>
            <TaxonomicPopoverMenu
                groupType={TaxonomicFilterGroupType.EventProperties}
                groupTypes={[TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.HogQLExpression]}
                triggerVariant="input"
                onChange={jest.fn()}
            />
        </Provider>
    )
}

describe('TaxonomicPopoverMenu', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
        apiGet.mockReset()
        apiGet.mockImplementation(emptyPaginated)
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
        useMocks({})
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => cleanup())

    it('renders the placeholder input + filter-icon button before arming', () => {
        renderInputTriggerPopoverMenu()

        expect(screen.getByTestId('taxonomic-filter-menu-input')).toBeInTheDocument()
        expect(screen.getByLabelText('Open filter menu')).toBeInTheDocument()
    })

    it('arms to the dropdown menu (not the combobox) when the filter icon is clicked from the resting trigger', async () => {
        renderInputTriggerPopoverMenu()

        await userEvent.click(screen.getByLabelText('Open filter menu'))

        // The icon arms straight to the menu — its "HogQL expression" entry confirms it.
        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-filter-menu-hogql')).toBeInTheDocument()
        })
        // It must NOT open the combobox: the icon click must not bubble to the
        // input's focus handler, which would arm the combobox instead.
        expect(screen.queryByTestId('menu-filter-search')).not.toBeInTheDocument()
    })

    it('reopens warehouse configuration with the selected fields instead of table defaults', async () => {
        ;(performQuery as jest.Mock).mockResolvedValue({
            tables: {
                orders: {
                    id: 'orders-table',
                    name: 'orders',
                    type: 'data_warehouse',
                    id_field: 'id',
                    fields: {
                        id: { name: 'id', type: 'string' },
                        distinct_id: { name: 'distinct_id', type: 'string' },
                    },
                },
            },
            joins: [],
            results: [],
        })
        const unmount = databaseTableListLogic.mount()
        const onChange = jest.fn()
        const filter: FunnelDatawarehouseFilter = {
            type: EntityTypes.DATA_WAREHOUSE,
            id: 'orders',
            table_name: 'orders',
            id_field: 'distinct_id',
            timestamp_field: 'created_at',
            aggregation_target_field: 'distinct_id',
        }
        try {
            databaseTableListLogic.actions.loadDatabase({ force: true })
            await waitFor(() => expect(databaseTableListLogic.values.dataWarehouseTablesMap.orders).not.toBeUndefined())
            render(
                <Provider>
                    <TaxonomicPopoverMenu
                        groupType={TaxonomicFilterGroupType.DataWarehouse}
                        groupTypes={[TaxonomicFilterGroupType.DataWarehouse]}
                        value="orders"
                        filter={filter}
                        dataWarehousePopoverFields={[{ key: 'id_field', label: 'Data Warehouse Join Key' }]}
                        onChange={onChange}
                    />
                </Provider>
            )

            await userEvent.click(screen.getByText('orders', { selector: 'span' }))
            expect(await screen.findByText('distinct_id', { selector: '[data-slot="item-title"]' })).toBeInTheDocument()
            await userEvent.click(screen.getByText('Select', { exact: true }))

            expect(onChange).toHaveBeenCalledWith(
                'orders',
                TaxonomicFilterGroupType.DataWarehouse,
                expect.objectContaining({ id_field: 'distinct_id', fields: expect.any(Object) }),
                expect.any(Object)
            )
        } finally {
            unmount()
        }
    })
})
