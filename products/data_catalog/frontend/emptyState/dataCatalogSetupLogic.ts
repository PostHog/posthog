import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { dataCatalogMetricsList } from '../generated/api'
import { metricsLogic } from '../metricsLogic'

/**
 * Setup detection for the data catalog empty state. The catalog is built around
 * metrics: certifications and relationships describe warehouse tables the product
 * did not create, so a project with no metric has nothing catalogued yet.
 */
export const dataCatalogSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.DATA_CATALOG,
    path: ['products', 'data_catalog', 'frontend', 'emptyState', 'dataCatalogSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await dataCatalogMetricsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
    // The empty state creates the first metric in a modal, without leaving the scene,
    // so no remount would re-run detection and the gate would keep hiding what was created.
    recheckActionTypes: () => [metricsLogic.actionTypes.loadMetricsSuccess],
})
