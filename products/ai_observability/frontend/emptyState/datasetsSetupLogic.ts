import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { datasetsList } from '../generated/api'

/**
 * Archived datasets must keep the list accessible so users can restore them.
 */
export const datasetsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.LLM_DATASETS,
    path: ['products', 'ai_observability', 'frontend', 'emptyState', 'datasetsSetupLogic'],
    cacheHasData: true,
    revalidateCachedHasData: true,
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await datasetsList(projectId, { limit: 1 })
        if (response.count > 0) {
            return 'has-data'
        }
        const archivedResponse = await datasetsList(projectId, { limit: 1, archived: true })
        return archivedResponse.count > 0 ? 'has-data' : 'needs-setup'
    },
})
