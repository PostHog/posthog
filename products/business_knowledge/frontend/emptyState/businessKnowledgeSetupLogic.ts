import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { businessKnowledgeRepositoriesStatusRetrieve, businessKnowledgeSourcesList } from '../generated/api'
import { businessKnowledgeLogic } from '../scenes/sources/businessKnowledgeLogic'

/**
 * Setup detection for the business knowledge empty state. Creation-first: one
 * knowledge source of any type counts as set up, and so does a selected GitHub
 * repository, which is read on demand and never becomes a source. The empty
 * state's own "Add source" modal submits through the scene logic, so re-detect
 * on those submits.
 */
export const businessKnowledgeSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
    path: ['products', 'business_knowledge', 'frontend', 'emptyState', 'businessKnowledgeSetupLogic'],
    cacheHasData: true,
    revalidateCachedHasData: true,
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await businessKnowledgeSourcesList(projectId, { limit: 1 })
        if (response.count > 0) {
            return 'has-data'
        }
        // A failed check is not an empty answer: `needs-setup` would lock a repository-only project out
        // of Libraries and clear its cached answer, while `null` keeps the factory's fail-open behavior.
        const connection = await businessKnowledgeRepositoriesStatusRetrieve(projectId).catch(() => null)
        if (!connection) {
            return null
        }
        return connection.connected && connection.repos.length > 0 ? 'has-data' : 'needs-setup'
    },
    recheckActionTypes: () => [
        businessKnowledgeLogic.actionTypes.submitTextSourceSuccess,
        businessKnowledgeLogic.actionTypes.submitUrlSourceSuccess,
        businessKnowledgeLogic.actionTypes.submitFileSourceSuccess,
    ],
})
