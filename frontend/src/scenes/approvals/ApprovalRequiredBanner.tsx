import { router } from 'kea-router'

import { LemonBanner, LemonButton, lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export interface ApprovalRequiredBannerProps {
    changeRequestId: string
    actionDescription?: string
    onDismiss?: () => void
}

export function ApprovalRequiredBanner({
    changeRequestId,
    actionDescription,
    onDismiss,
}: ApprovalRequiredBannerProps): JSX.Element {
    return (
        <LemonBanner
            type="info"
            onClose={onDismiss}
            action={
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => {
                        router.actions.push(urls.approval(changeRequestId))
                    }}
                >
                    View approval
                </LemonButton>
            }
        >
            <div>
                <strong>Approval required</strong>
                <div className="text-sm mt-1">
                    {actionDescription
                        ? `Your request to ${actionDescription} has been submitted for approval.`
                        : 'Your change request has been submitted for approval.'}
                </div>
            </div>
        </LemonBanner>
    )
}

export function showApprovalRequiredToast(changeRequestId: string, actionDescription?: string): void {
    lemonToast.info(
        <div>
            <strong>Approval required</strong>
            <div className="text-sm mt-1">
                {actionDescription
                    ? `Your request to ${actionDescription} has been submitted for approval.`
                    : 'Your change request has been submitted for approval.'}
            </div>
            <LemonButton
                type="secondary"
                size="small"
                className="mt-2"
                onClick={() => {
                    router.actions.push(urls.approval(changeRequestId))
                }}
            >
                View approval
            </LemonButton>
        </div>
    )
}

export interface ApprovalRequiredResponse {
    change_request_id: string
    detail?: string
}

export function isApprovalRequiredResponse(response: Response, data: any): data is ApprovalRequiredResponse {
    return response.status === 202 && data?.change_request_id
}

export async function handleApprovalResponse<T>(
    response: Response,
    options?: {
        actionDescription?: string
        showToast?: boolean
    }
): Promise<T> {
    const data = await response.json()

    if (isApprovalRequiredResponse(response, data)) {
        if (options?.showToast !== false) {
            showApprovalRequiredToast(data.change_request_id, options?.actionDescription)
        }
        throw new ApprovalRequiredError(data.change_request_id, data.detail)
    }

    return data
}

export class ApprovalRequiredError extends Error {
    constructor(
        public changeRequestId: string,
        public detail?: string
    ) {
        super(detail || 'This action requires approval')
        this.name = 'ApprovalRequiredError'
    }
}
