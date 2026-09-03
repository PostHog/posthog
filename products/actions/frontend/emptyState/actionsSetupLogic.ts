import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { actionsList } from '../generated/api'

/**
 * Setup detection for the actions empty state. Actions are a creation-first
 * product, so "set up" simply means the project has at least one action - no event
 * or traffic signal involved.
 */
export const actionsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.ACTIONS,
    path: ['products', 'actions', 'frontend', 'emptyState', 'actionsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await actionsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
