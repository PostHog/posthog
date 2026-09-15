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

    it.each(['before opening', 'after opening'] as const)(
        'reopens warehouse configuration when the schema loads %s',
        async (schemaTiming) => {
            const schema = {
                tables: {
                    orders: {
                        id: 'orders-table',
                        name: 'orders',
                        type: 'data_warehouse',
                        id_field: 'id',
                        fields: {
                            id: { name: 'id', type: 'string' },
                            distinct_id: { name: 'distinct_id', type: 'string' },
                            created_at: { name: 'created_at', type: 'datetime' },
                        },
                    },
                },
                joins: [],
                results: [],
            }
            let resolveSchema!: (value: typeof schema) => void
            const schemaResponse = new Promise<typeof schema>((resolve) => {
                resolveSchema = resolve
            })
            ;(performQuery as jest.Mock).mockReturnValue(schemaResponse)
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
                if (schemaTiming === 'before opening') {
                    resolveSchema(schema)
                    await waitFor(() =>
                        expect(databaseTableListLogic.values.dataWarehouseTablesMap.orders).not.toBeUndefined()
                    )
                }
                render(
                    <Provider>
                        <TaxonomicPopoverMenu
                            groupType={TaxonomicFilterGroupType.DataWarehouse}
                            groupTypes={[TaxonomicFilterGroupType.DataWarehouse]}
                            value="orders"
                            filter={filter}
                            dataWarehousePopoverFields={[
                                { key: 'timestamp_field', label: 'Timestamp Field' },
                                { key: 'id_field', label: 'Data Warehouse Join Key' },
                            ]}
                            onChange={onChange}
                        />
                    </Provider>
                )

                await userEvent.click(screen.getByText('orders', { selector: 'span' }))
                if (schemaTiming === 'after opening') {
                    expect(screen.getByText('Select a value')).toBeInTheDocument()
                    resolveSchema(schema)
                }
                expect(
                    await screen.findByText('created_at', { selector: '[data-slot="item-title"]' })
                ).toBeInTheDocument()
                await userEvent.click(screen.getByText('created_at', { selector: '[data-slot="item-title"]' }))
                expect(await screen.findByPlaceholderText('Search columns')).toBeInTheDocument()
                expect(
                    await screen.findByText('distinct_id', { selector: '[data-slot="item-title"]' })
                ).toBeInTheDocument()
                await userEvent.keyboard('{Escape}')
                await userEvent.click(screen.getByText('Data Warehouse Join Key', { selector: 'button' }))
                expect(
                    await screen.findByText('distinct_id', { selector: '[data-slot="item-title"]' })
                ).toBeInTheDocument()
                await userEvent.click(screen.getByText('Select', { exact: true }))

                expect(onChange).toHaveBeenCalledWith(
                    'orders',
                    TaxonomicFilterGroupType.DataWarehouse,
                    expect.objectContaining({
                        timestamp_field: 'created_at',
                        id_field: 'distinct_id',
                        fields: expect.any(Object),
                    }),
                    expect.any(Object)
                )
            } finally {
                unmount()
            }
        }
    )
})
