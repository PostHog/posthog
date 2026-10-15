import posthog from 'posthog-js'

import { cohortsUsedInRetrieve } from 'products/cohorts/frontend/generated/api'
import type { CohortUsedInWorkflowsBlockApi } from 'products/cohorts/frontend/generated/api.schemas'

// pinned: error code the cohort API returns when workflows block a change, see posthog/api/cohort.py
export const COHORT_USED_BY_WORKFLOWS_ERROR_CODE = 'cohort_used_by_workflows'

/**
 * The active workflows that block deleting this cohort or editing it so it stops updating in real
 * time, or null when nothing blocks it. A failed check returns null, because the API still refuses
 * the change and the caller then shows the API error.
 */
export async function loadBlockingWorkflows(
    projectId: number | string,
    cohortId: number
): Promise<CohortUsedInWorkflowsBlockApi | null> {
    try {
        const usedIn = await cohortsUsedInRetrieve(String(projectId), cohortId)
        return usedIn.workflows.total > 0 ? usedIn.workflows : null
    } catch (error) {
        posthog.captureException(error, { feature: 'cohort-blocking-workflows' })
        return null
    }
}
