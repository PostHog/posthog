import { lemonToast } from '@posthog/lemon-ui'

/**
 * Handle 409 Approval Required errors from API calls.
 *
 * @returns true if the error was an approval-related 409, false otherwise
 */
export function handleApprovalRequired(
    error: { status?: number; detail?: string } | null | undefined,
    resourceType: string,
    resourceId: string | number
): boolean {
    if (error?.status === 409) {
        lemonToast.warning(error.detail || 'This action requires approval.')

        import('scenes/approvals/changeRequestsLogic').then(({ changeRequestsLogic }) => {
            changeRequestsLogic({
                resourceType,
                resourceId: String(resourceId),
            }).actions.loadChangeRequests()
        })
        return true
    }
    return false
}
