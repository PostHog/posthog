import { useValues } from 'kea'

import { InitialBillingLimitNotice } from 'scenes/billing/InitialBillingLimitNotice'

import { ProductKey } from '~/queries/schema/schema-general'

import { sourceManagementLogic } from '../../../shared/logics/sourceManagementLogic'

export const BillingLimitNotice = (): JSX.Element | null => {
    const { dataWarehouseSources, selfManagedTables } = useValues(sourceManagementLogic)

    const hasSources =
        (dataWarehouseSources?.results && dataWarehouseSources?.results.length > 0) || selfManagedTables?.length > 0

    return hasSources ? <InitialBillingLimitNotice product_key={ProductKey.DATA_WAREHOUSE} /> : null
}
