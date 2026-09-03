import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { evaluationDirectoriesList, evaluationsList } from '../generated/api'

/**
 * Setup detection for the evaluations empty state. Creation-first: an evaluation
 * or a directory in the project counts as set up, matching the scene's own
 * "first evaluation" check so a person with only a directory still reaches it.
 */
export const evaluationsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.LLM_EVALUATIONS,
    path: ['products', 'ai_observability', 'frontend', 'emptyState', 'evaluationsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const [evaluations, directories] = await Promise.all([
            evaluationsList(projectId, { limit: 1 }),
            evaluationDirectoriesList(projectId),
        ])
        return evaluations.count > 0 || directories.length > 0 ? 'has-data' : 'needs-setup'
    },
})
