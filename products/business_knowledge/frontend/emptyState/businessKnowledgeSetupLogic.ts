import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { businessKnowledgeSourcesList } from '../generated/api'
import { businessKnowledgeLogic } from '../scenes/businessKnowledgeLogic'

/**
 * Setup detection for the business knowledge empty state. Creation-first: one
 * knowledge source of any type counts as set up. The empty state's own "Add
 * source" modal submits through the scene logic, so re-detect on those submits.
 */
export const businessKnowledgeSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
    path: ['products', 'business_knowledge', 'frontend', 'emptyState', 'businessKnowledgeSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await businessKnowledgeSourcesList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
    recheckActionTypes: () => [
        businessKnowledgeLogic.actionTypes.submitTextSourceSuccess,
        businessKnowledgeLogic.actionTypes.submitUrlSourceSuccess,
        businessKnowledgeLogic.actionTypes.submitFileSourceSuccess,
    ],
})
