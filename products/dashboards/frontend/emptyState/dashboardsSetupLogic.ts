import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { dashboardsList } from '../generated/api'

/**
 * Setup detection for the dashboards empty state. Dashboards are a creation-first
 * product, so "set up" simply means the project has at least one dashboard - no
 * event or traffic signal involved.
 */
export const dashboardsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.DASHBOARDS,
    path: ['products', 'dashboards', 'frontend', 'emptyState', 'dashboardsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await dashboardsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
