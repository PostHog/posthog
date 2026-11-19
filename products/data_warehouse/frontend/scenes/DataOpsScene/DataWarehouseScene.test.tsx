import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as dwApi from 'products/data_warehouse/frontend/generated/api'

import { DataWarehouseScene } from './DataWarehouseScene'
import { warehouseProvisioningLogic } from './tabs/warehouseProvisioningLogic'
import { warehouseStatusFixture } from './tabs/warehouseStatusFixtures'

describe('DataWarehouseScene', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    // The password is shown once, and provisioning finishing moves the scene off the Settings tab.
    it('shows the one-time password banner while another tab is active', async () => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue(warehouseStatusFixture())
        jest.spyOn(dwApi, 'dataWarehouseManagedWarehouseDataStatusRetrieve').mockReturnValue(new Promise(() => {}))
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DATA_WAREHOUSE_SCENE], {
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true,
        })
        render(
            <Provider>
                <DataWarehouseScene />
            </Provider>
        )

        // The tab bar only exists once the warehouse is ready, and Overview is its first tab.
        expect(await screen.findByText('Monitoring')).toBeInTheDocument()
        warehouseProvisioningLogic.actions.setInitialPassword('example-password')

        expect(await screen.findByText("Save your password now. It won't be shown again.")).toBeInTheDocument()
        // CodeSnippet can split its text across elements, so this reads the page text.
        expect(document.body.textContent).toContain('example-password')
    })
})
