import { lemonToast } from '@posthog/lemon-ui'

/**
 * Handle 409 Approval Required errors from API calls.
 *
 * @returns true if the error was an approval-required 409, false otherwise
 */
export function handleApprovalRequired(
    error: { status?: number } | null | undefined,
    resourceType: string,
    resourceId: string | number
): boolean {
    if (error?.status === 409) {
        lemonToast.warning('A change request has been created and is pending approval.')

        import('scenes/approvals/pendingChangeRequestLogic').then(({ pendingChangeRequestLogic }) => {
            pendingChangeRequestLogic({
                resourceType,
                resourceId: String(resourceId),
            }).actions.loadChangeRequests()
        })
        return true
    }
    return false
}
