import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

/** Renders its children only while the managed warehouse console flag is on. Without it the page does not exist and nothing below mounts. */
export function WarehouseConsoleGate({ children }: { children: React.ReactNode }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]) {
        return <NotFound object="page" />
    }
    return <>{children}</>
}
