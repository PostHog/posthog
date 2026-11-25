import { BindLogic, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { WarehousePageKind, warehouseConsoleRedirectLogic } from './warehouseConsoleRedirectLogic'

/**
 * Renders its children only while the warehouse console flag is on. Without it the page does not exist and nothing below mounts.
 * With the flag on it also mounts the redirect between the upsell page and the pages that need a warehouse.
 */
export function WarehouseConsoleGate({
    kind = 'console',
    children,
}: {
    kind?: WarehousePageKind
    children: React.ReactNode
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]) {
        return <NotFound object="page" />
    }
    return (
        <BindLogic logic={warehouseConsoleRedirectLogic} props={{ kind }}>
            {children}
        </BindLogic>
    )
}
