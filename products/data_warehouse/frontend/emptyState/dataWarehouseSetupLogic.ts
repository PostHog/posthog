import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'

import { ProductKey } from '~/queries/schema/schema-general'

/**
 * Setup detection for the data warehouse empty state. A managed source counts
 * from the moment it's created (its row with sync status is the useful scene),
 * and self-managed or direct-connect setups surface as warehouse tables.
 */
export const dataWarehouseSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.DATA_WAREHOUSE,
    path: ['products', 'data_warehouse', 'frontend', 'emptyState', 'dataWarehouseSetupLogic'],
    detect: async () => {
        const [sources, tables] = await Promise.all([
            api.externalDataSources.list(),
            api.dataWarehouseTables.list({ limit: 1 }),
        ])
        return sources.results.length > 0 || tables.results.length > 0 ? 'has-data' : 'needs-setup'
    },
})
