import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { externalDataSourcesConnectionsList } from 'products/warehouse_sources/frontend/generated/api'

import {
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
            },
        ])
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads connection options on mount', async () => {
        logic = connectionSelectorLogic()
        logic.mount()

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
            ])
        )
        expect(logic.values.connectionSelectOptions[1].options).toEqual(
            expect.arrayContaining([expect.not.objectContaining({ managementUrl: expect.anything() })])
        )
    })

    it('derives the selected connection value from sql editor state', async () => {
        expect(getConnectionSelectorValue(null, true, undefined)).toEqual(LOADING_CONNECTIONS)
        expect(
            getConnectionSelectorValue(
                [{ id: 'conn-123', prefix: 'warehouse', engine: 'postgres' }] as any,
                false,
                'conn-123'
            )
        ).toEqual('conn-123')
        expect(
            getConnectionSelectorValue(
                [{ id: 'conn-123', prefix: 'warehouse', engine: 'postgres' }] as any,
                false,
                'missing'
            )
        ).toEqual(POSTHOG_WAREHOUSE)
    })
})
