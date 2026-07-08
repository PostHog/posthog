import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { showApprovalRequiredToast } from 'scenes/approvals/ApprovalRequiredBanner'
import { dispatchChangeRequestCreated } from 'scenes/approvals/utils'

import { featureFlagsPartialUpdate } from 'products/feature_flags/frontend/generated/api'
import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

/**
 * Toggle a flag's `active` state in any project of the current organization, with shared
 * toast handling (success, approval-required 409, permission/other errors).
 * Returns the updated flag, or `null` if the update did not go through.
 */
export async function updateFlagActiveInProject({
    teamId,
    flagId,
    active,
}: {
    teamId: number
    flagId: number
    active: boolean
}): Promise<FeatureFlagApi | null> {
    const actionDescription = `${active ? 'enable' : 'disable'} this feature flag`
    try {
        const updatedFlag = await featureFlagsPartialUpdate(String(teamId), flagId, { active })
        lemonToast.success(`Feature flag ${active ? 'enabled' : 'disabled'}`)
        return updatedFlag
    } catch (e: any) {
        if (e?.status === 409 && e?.data?.change_request_id) {
            showApprovalRequiredToast(e.data.change_request_id, actionDescription)
            dispatchChangeRequestCreated({ resourceType: 'feature_flag', resourceId: flagId })
        } else {
            lemonToast.error(e?.detail || e?.data?.detail || `Failed to ${actionDescription}`)
        }
        return null
    }
}
