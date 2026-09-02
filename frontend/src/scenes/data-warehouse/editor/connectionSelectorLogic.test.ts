import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { externalDataSourcesConnectionsList } from 'products/warehouse_sources/frontend/generated/api'
import type { ExternalDataSourceConnectionOptionApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import {
    addHiddenSelectedConnectionOption,
    connectionSelectorLogic,
    getConnectionSelectorValue,
    LOADING_CONNECTIONS,
    POSTHOG_WAREHOUSE,
} from './connectionSelectorLogic'

jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataSourcesConnectionsList: jest.fn(),
}))

const mockConnectionsList = externalDataSourcesConnectionsList as jest.Mock

describe('connectionSelectorLogic', () => {
    let logic: ReturnType<typeof connectionSelectorLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockConnectionsList.mockReset().mockResolvedValue([
            {
                id: 'conn-123',
                prefix: 'warehouse',
                engine: 'postgres',
                source_type: 'Postgres',
                access_method: 'direct',
                supports_hogql: true,
                is_builtin_managed_warehouse: false,
            },
            {
                id: 'conn-456',
                prefix: 'prod',
                engine: null,
                source_type: 'MySQL',
                access_method: 'warehouse',
                supports_hogql: true,
                is_builtin_managed_warehouse: false,
            },
        ])
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('does not fetch on mount — embedded editors mount this logic without the selector', async () => {
        logic = connectionSelectorLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockConnectionsList).not.toHaveBeenCalled()
    })

    it('loads connection options when the selector requests them', async () => {
        logic = connectionSelectorLogic()
        logic.mount()
        logic.actions.maybeLoadConnectionOptions()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockConnectionsList).toHaveBeenCalledTimes(1)
        expect(logic.values.connectionSelectOptions[0].options).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ value: POSTHOG_WAREHOUSE }),
                expect.objectContaining({
                    value: 'conn-123',
                    label: 'warehouse (Postgres)',
                    managementUrl: urls.dataWarehouseSource('managed-conn-123'),
                }),
                // Synced source: no detected engine — label derives from source_type + synced marker
                expect.objectContaining({
                    value: 'conn-456',
                    label: 'prod (MySQL · synced)',
                    managementUrl: urls.dataWarehouseSource('managed-conn-456'),
                }),
            ])
        )
        expect(logic.values.connectionSelectOptions[1].options).toEqual(
            expect.arrayContaining([expect.not.objectContaining({ managementUrl: expect.anything() })])
        )
    })

    it('shows a provisioned managed warehouse below ClickHouse', async () => {
        mockConnectionsList.mockResolvedValue([
            {
                id: 'conn-duck',
                prefix: 'managed_warehouse',
                engine: 'duckdb',
                source_type: 'Postgres',
                access_method: 'direct',
                supports_hogql: true,
                is_builtin_managed_warehouse: true,
            },
        ])
        logic = connectionSelectorLogic()
        logic.mount()
        logic.actions.maybeLoadConnectionOptions()

        await expectLogic(logic).toFinishAllListeners()

        const [clickHouseOption, managedWarehouseOption] = logic.values.connectionSelectOptions[0].options
        expect(clickHouseOption).toEqual(
            expect.objectContaining({ value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' })
        )
        expect(managedWarehouseOption).toEqual(
            expect.objectContaining({ value: 'conn-duck', label: 'PostHog (Managed warehouse)' })
        )
        expect(managedWarehouseOption.iconSrc).toEqual(clickHouseOption.iconSrc)
        expect(managedWarehouseOption).not.toHaveProperty('managementUrl')
    })

    it('keeps the auto-provisioned Duckgres source external when the backend marks it external', async () => {
        mockConnectionsList.mockResolvedValue([
            {
                id: 'conn-duck',
                prefix: 'managed_warehouse',
                description: 'Managed warehouse (auto-provisioned)',
                engine: 'duckdb',
                source_type: 'Postgres',
                access_method: 'direct',
                supports_hogql: true,
                is_builtin_managed_warehouse: false,
            },
        ])
        logic = connectionSelectorLogic()
        logic.mount()
        logic.actions.maybeLoadConnectionOptions()

        await expectLogic(logic).toFinishAllListeners()

        const externalOption = logic.values.connectionSelectOptions[0].options[1]
        expect(externalOption).toEqual(
            expect.objectContaining({
                value: 'conn-duck',
                label: 'Managed warehouse (auto-provisioned) (DuckDB)',
                managementUrl: urls.dataWarehouseSource('managed-conn-duck'),
            })
        )
    })

    it('derives the selected connection value from sql editor state', async () => {
        expect(getConnectionSelectorValue(true, undefined)).toEqual(LOADING_CONNECTIONS)
        expect(getConnectionSelectorValue(false, 'conn-123')).toEqual('conn-123')
        expect(getConnectionSelectorValue(false, 'missing')).toEqual('missing')
    })

    it.each([
        ['reader after the flag is disabled', 'reader-connection', 'legacy-connection'],
        ['legacy connection after the flag is enabled', 'legacy-connection', 'reader-connection'],
    ])('keeps a hidden selected %s instead of displaying ClickHouse', (_name, selectedId, visibleId) => {
        const optionGroups = [
            {
                options: [
                    { value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' },
                    { value: visibleId, label: 'Visible managed warehouse' },
                ],
            },
        ]
        const connectionOptions = [{ id: visibleId }] as ExternalDataSourceConnectionOptionApi[]

        const displayedOptions = addHiddenSelectedConnectionOption(optionGroups, connectionOptions, false, selectedId)

        expect(getConnectionSelectorValue(false, selectedId)).toEqual(selectedId)
        expect(displayedOptions[0].options).toContainEqual({
            value: selectedId,
            label: 'Selected connection (hidden)',
            hidden: true,
        })
    })
})
