import { LemonButton, LemonDialog, LemonInput, lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ChangeRequest, ChangeRequestState } from '~/types'

export interface ChangeRequestActionsProps {
    changeRequest: ChangeRequest
    onApprove: (id: string) => void
    onReject: (id: string, reason?: string) => void
    onCancel: (id: string, reason?: string) => void
    showViewButton?: boolean
}

export function ChangeRequestActions({
    changeRequest,
    onApprove,
    onReject,
    onCancel,
    showViewButton = false,
}: ChangeRequestActionsProps): JSX.Element {
    const canApprove = changeRequest.can_approve
    const canCancel = changeRequest.can_cancel
    const userDecision = changeRequest.user_decision

    const actions: JSX.Element[] = []

    // View Request button (only show if explicitly requested)
    if (showViewButton && (canApprove || canCancel)) {
        actions.push(
            <LemonButton key="view" type="secondary" size="small" to={urls.approval(changeRequest.id)}>
                View Request
            </LemonButton>
        )
    }

    // Approve/Reject buttons (only if pending, user can approve, AND hasn't already voted)
    const isPending = changeRequest.state === ChangeRequestState.Pending
    if (isPending && canApprove && !userDecision) {
        // Approve button
        actions.push(
            <LemonButton
                key="approve"
                type="primary"
                size="small"
                onClick={() => {
                    LemonDialog.open({
                        title: 'Approve this change request?',
                        content: (
                            <div className="text-sm text-secondary">
                                This will add your approval to the change request and may automatically apply the
                                change.
                            </div>
                        ),
                        primaryButton: {
                            children: 'Approve',
                            type: 'primary',
                            onClick: () => onApprove(changeRequest.id),
                            size: 'small',
                        },
                        secondaryButton: {
                            children: 'Cancel',
                            type: 'tertiary',
                            size: 'small',
                        },
                    })
                }}
            >
                Approve
            </LemonButton>
        )

        // Reject button (only for approvers)
        actions.push(
            <LemonButton
                key="reject"
                type="secondary"
                status="danger"
                size="small"
                onClick={() => {
                    LemonDialog.open({
                        title: 'Reject this change request?',
                        content: (
                            <div>
                                <div className="text-sm text-secondary mb-2">
                                    This will reject the change request and prevent it from being applied.
                                </div>
                                <LemonInput id="reject-reason" placeholder="Reason for rejection (required)" />
                            </div>
                        ),
                        primaryButton: {
                            children: 'Reject',
                            type: 'primary',
                            status: 'danger',
                            onClick: () => {
                                const reason = (
                                    document.getElementById('reject-reason') as HTMLInputElement
                                )?.value?.trim()
                                if (reason) {
                                    onReject(changeRequest.id, reason)
                                } else {
                                    lemonToast.error('Please provide a reason for rejection')
                                }
                            },
                            size: 'small',
                        },
                        secondaryButton: {
                            children: 'Cancel',
                            type: 'tertiary',
                            size: 'small',
                        },
                    })
                }}
            >
                Reject
            </LemonButton>
        )
    }

    // Cancel request button (only if pending and user can cancel)
    if (isPending && canCancel) {
        actions.push(
            <LemonButton
                key="cancel"
                type="secondary"
                size="small"
                onClick={() => {
                    LemonDialog.open({
                        title: 'Cancel this change request?',
                        content: (
                            <div>
                                <div className="text-sm text-secondary mb-2">
                                    This will cancel your change request and it will not be applied.
                                </div>
                                <LemonInput id="cancel-reason" placeholder="Reason for canceling (optional)" />
                            </div>
                        ),
                        primaryButton: {
                            children: 'Cancel request',
                            type: 'primary',
                            status: 'danger',
                            onClick: () => {
                                const reason = (document.getElementById('cancel-reason') as HTMLInputElement)?.value
                                onCancel(changeRequest.id, reason || undefined)
                            },
                            size: 'small',
                        },
                        secondaryButton: {
                            children: 'Nevermind',
                            type: 'tertiary',
                            size: 'small',
                        },
                    })
                }}
            >
                Cancel request
            </LemonButton>
        )
    }

    return <>{actions}</>
}
