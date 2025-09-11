import { useValues } from 'kea'

import { InitialBillingLimitNotice } from 'scenes/billing/InitialBillingLimitNotice'

import { ProductKey } from '~/types'

import { dataWarehouseSettingsLogic } from './settings/dataWarehouseSettingsLogic'

export const DataWarehouseInitialBillingLimitNotice = (): JSX.Element | null => {
    const { dataWarehouseSources, selfManagedTables } = useValues(dataWarehouseSettingsLogic)

    const hasSources =
        (dataWarehouseSources?.results && dataWarehouseSources?.results.length > 0) || selfManagedTables?.length > 0

    return hasSources ? <InitialBillingLimitNotice product_key={ProductKey.DATA_WAREHOUSE} /> : null
}
