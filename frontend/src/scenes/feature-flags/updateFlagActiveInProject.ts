import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { showApprovalRequiredToast } from 'scenes/approvals/ApprovalRequiredBanner'
import { dispatchChangeRequestCreated } from 'scenes/approvals/utils'

import { featureFlagsPartialUpdate } from 'products/feature_flags/frontend/generated/api'
import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

/** Key for the per-row in-flight maps shared by the Projects tab toggles. */
export function flagToggleKey(teamId: number, flagId: number): string {
    return `${teamId}:${flagId}`
}

/** Confirmation dialog shared by the Projects tab toggles, naming the target project. */
export function confirmFlagActiveToggleInProject({
    teamName,
    active,
    onConfirm,
}: {
    teamName: string
    active: boolean
    onConfirm: () => void
}): void {
    LemonDialog.open({
        title: `${active ? 'Enable' : 'Disable'} this flag in ${teamName}?`,
        description: `This flag will be immediately ${
            active ? 'rolled out to' : 'rolled back from'
        } the users matching the release conditions in ${teamName}.`,
        primaryButton: {
            children: 'Confirm',
            type: 'primary',
            status: active ? 'default' : 'danger',
            size: 'small',
            onClick: onConfirm,
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

/**
 * Handle an approval-required 409 from a flag update: show the approval toast and announce
 * the created change request. Returns whether the error was an approval-required response.
 */
export function handleFlagApprovalRequired(e: any, flagId: number, actionDescription: string): boolean {
    if (e?.status === 409 && e?.data?.change_request_id) {
        showApprovalRequiredToast(e.data.change_request_id, actionDescription)
        dispatchChangeRequestCreated({ resourceType: 'feature_flag', resourceId: flagId })
        return true
    }
    return false
}

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
        if (!handleFlagApprovalRequired(e, flagId, actionDescription)) {
            lemonToast.error(e?.detail || e?.data?.detail || `Failed to ${actionDescription}`)
        }
        return null
    }
}
