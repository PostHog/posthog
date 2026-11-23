import { useValues } from 'kea'

import { HoglakeCredentials } from '../DataOpsScene/tabs/HoglakeCredentials'
import { MyHoglakeCredentials } from '../DataOpsScene/tabs/MyHoglakeCredentials'
import { warehouseProvisioningLogic } from '../DataOpsScene/tabs/warehouseProvisioningLogic'

/**
 * Direct catalog credentials. These are the existing LemonUI components from Data ops, mounted unchanged
 * until they get a quill version. A DuckLake catalog has nothing behind them, so they show only for a hoglake one.
 */
export function WarehouseDirectCredentials(): JSX.Element | null {
    const { warehouseStatus } = useValues(warehouseProvisioningLogic)

    if (warehouseStatus?.trino?.state !== 'ready' || !warehouseStatus.trino.hoglake) {
        return null
    }
    return (
        <section aria-label="Direct catalog credentials" className="flex flex-col gap-3">
            <MyHoglakeCredentials />
            <HoglakeCredentials />
        </section>
    )
}
