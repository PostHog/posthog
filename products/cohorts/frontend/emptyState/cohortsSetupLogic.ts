import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { cohortsList } from '../generated/api'

/**
 * Setup detection for the cohorts empty state. Cohorts are a creation-first
 * product, so "set up" simply means the project has at least one cohort - no event
 * or traffic signal involved.
 */
export const cohortsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.COHORTS,
    path: ['products', 'cohorts', 'frontend', 'emptyState', 'cohortsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        // Only the count matters here, so ask for the trimmed payload.
        const response = await cohortsList(projectId, { limit: 1, basic: true })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
