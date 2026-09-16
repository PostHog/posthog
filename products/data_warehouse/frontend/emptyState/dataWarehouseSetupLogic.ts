import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { externalDataSourcesExistsRetrieve } from 'products/warehouse_sources/frontend/generated/api'

/**
 * Setup detection for the data warehouse empty state. A managed source counts
 * from the moment it's created (its row with sync status is the useful scene),
 * and self-managed or direct-connect setups surface as warehouse tables.
 */
export const dataWarehouseSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.DATA_WAREHOUSE,
    path: ['products', 'data_warehouse', 'frontend', 'emptyState', 'dataWarehouseSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const [sources, tables] = await Promise.all([
            externalDataSourcesExistsRetrieve(projectId),
            api.dataWarehouseTables.list({ limit: 1 }),
        ])
        return sources.exists || tables.results.length > 0 ? 'has-data' : 'needs-setup'
    },
})
