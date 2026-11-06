import { router } from 'kea-router'

import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { externalDataSourcesExistsRetrieve } from 'products/warehouse_sources/frontend/generated/api'

import { warehouseTablesList } from '../generated/api'

/**
 * Setup detection for the data warehouse empty state. A managed source counts
 * from the moment it's created (its row with sync status is the useful scene),
 * and self-managed or direct-connect setups surface as warehouse tables.
 */
export const dataWarehouseSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.DATA_WAREHOUSE,
    path: ['products', 'data_warehouse', 'frontend', 'emptyState', 'dataWarehouseSetupLogic'],
    cacheHasData: true,
    revalidateCachedHasData: true,
    recheckActionTypes: () => [router.actionTypes.locationChanged],
    detect: async () => {
        const [sources, tables] = await Promise.all([
            externalDataSourcesExistsRetrieve(String(teamLogic.values.currentTeamId)),
            warehouseTablesList(String(teamLogic.values.currentTeamId), { limit: 1, include_columns: false }),
        ])
        return sources.exists || tables.results.length > 0 ? 'has-data' : 'needs-setup'
    },
})
