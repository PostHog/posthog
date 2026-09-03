import type { CopyFlagsResponseApi } from 'products/feature_flags/frontend/generated/api.schemas'

export interface CreateInProjectsSummary {
    createdProjectIds: number[]
    updatedProjectIds: number[]
    pendingApprovalProjectIds: number[]
    failures: Array<{ projectId: number | null; errorMessage: string }>
}

/** Groups a copy_flags response by outcome so the create flow can report each group once. */
export function summarizeCreateInProjects(response: CopyFlagsResponseApi): CreateInProjectsSummary {
    return {
        createdProjectIds: response.success.filter((item) => !item.updated_existing).map((item) => item.team_id),
        updatedProjectIds: response.success.filter((item) => item.updated_existing).map((item) => item.team_id),
        pendingApprovalProjectIds: response.failed
            .filter((entry) => entry.approval_pending)
            .map((entry) => entry.project_id)
            .filter((id): id is number => id != null),
        failures: response.failed
            .filter((entry) => !entry.approval_pending)
            .map((entry) => ({
                projectId: entry.project_id ?? null,
                errorMessage: entry.error_message || 'Copy failed',
            })),
    }
}
