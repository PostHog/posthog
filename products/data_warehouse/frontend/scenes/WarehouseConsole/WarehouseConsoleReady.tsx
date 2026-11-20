import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { WarehouseConsoleReadyInner } from './WarehouseConsoleReadyInner'

/**
 * Renders its children only with the managed warehouse console flag on and the warehouse ready.
 * With the flag off it mounts nothing, so a page that adds console content behaves as it did before the console.
 */
export function WarehouseConsoleReady({ children }: { children: React.ReactNode }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]) {
        return null
    }
    return <WarehouseConsoleReadyInner>{children}</WarehouseConsoleReadyInner>
}
