import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { annotationsList } from '../generated/api'

/**
 * Setup detection for the annotations empty state. Annotations are a creation-first
 * product, so "set up" simply means the project has at least one annotation - no
 * event or traffic signal involved.
 */
export const annotationsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.ANNOTATIONS,
    path: ['products', 'annotations', 'frontend', 'emptyState', 'annotationsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await annotationsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
