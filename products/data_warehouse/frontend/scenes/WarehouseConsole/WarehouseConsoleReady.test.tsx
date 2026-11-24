import { render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { dataWarehouseWarehouseStatusRetrieve } from 'products/data_warehouse/frontend/generated/api'

import { trinoStatusFixture, warehouseStatusFixture } from '../DataOpsScene/tabs/warehouseStatusFixtures'
import { WarehouseConsoleReady } from './WarehouseConsoleReady'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseWarehouseStatusRetrieve: jest.fn(),
}))

const mockStatus = dataWarehouseWarehouseStatusRetrieve as jest.MockedFunction<
    typeof dataWarehouseWarehouseStatusRetrieve
>

describe('WarehouseConsoleReady', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        featureFlagLogic.mount()
        mockStatus.mockResolvedValue(warehouseStatusFixture({ trino: trinoStatusFixture() }))
    })

    it('mounts nothing and requests no warehouse status with the flag off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: false })
        render(
            <WarehouseConsoleReady>
                <div>console content</div>
            </WarehouseConsoleReady>
        )

        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(screen.queryByText('console content')).toBeNull()
        expect(mockStatus).not.toHaveBeenCalled()
    })

    it('shows its children once the flag is on and the warehouse is ready', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true })
        render(
            <WarehouseConsoleReady>
                <div>console content</div>
            </WarehouseConsoleReady>
        )

        expect(await screen.findByText('console content')).toBeTruthy()
        expect(mockStatus).toHaveBeenCalledTimes(1)
    })
})
