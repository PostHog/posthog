import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { hogFunctionsList } from '../generated/api'

/**
 * Setup detection for the transformations empty state. Transformations are creation-first
 * and only ever hog functions, so one transformation of any kind means the scene has a
 * list to show. Re-checks on every mount (the gate mounts it), which covers returning
 * from the creation page.
 */
export const transformationsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.PIPELINE_TRANSFORMATIONS,
    path: ['products', 'cdp', 'frontend', 'emptyState', 'transformationsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await hogFunctionsList(projectId, { type: ['transformation'], limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
