import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { datasetsList } from '../generated/api'

/**
 * Setup detection for the datasets empty state. Datasets are a creation-first
 * product, so "set up" simply means the project has at least one active dataset.
 */
export const datasetsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.LLM_DATASETS,
    path: ['products', 'ai_observability', 'frontend', 'emptyState', 'datasetsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await datasetsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
