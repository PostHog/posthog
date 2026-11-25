import { cleanup, render, screen } from '@testing-library/react'
import { useMountedLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as api from '../../generated/api'
import { WarehouseConsoleGate } from './WarehouseConsoleGate'
import { warehouseConsoleLogic } from './warehouseConsoleLogic'

function ConsolePage(): JSX.Element {
    // Mounting the console logic is what loads the warehouse status.
    useMountedLogic(warehouseConsoleLogic)
    return <div>console page</div>
}

describe('WarehouseConsoleGate', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('mounts nothing and makes no request while the flag is off, then mounts once the flag turns on', () => {
        const status = jest.spyOn(api, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue(null as never)
        featureFlagLogic.actions.setFeatureFlags([], {})
        const { rerender } = render(
            <WarehouseConsoleGate>
                <ConsolePage />
            </WarehouseConsoleGate>
        )

        expect(screen.queryByText('console page')).toBeNull()
        expect(status).not.toHaveBeenCalled()

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true })
        rerender(
            <WarehouseConsoleGate>
                <ConsolePage />
            </WarehouseConsoleGate>
        )

        expect(screen.getByText('console page')).toBeTruthy()
        expect(status).toHaveBeenCalled()
    })
})
