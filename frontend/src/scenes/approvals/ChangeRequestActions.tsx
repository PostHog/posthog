import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonMenu, lemonToast } from '@posthog/lemon-ui'

import { getChangeRequestButtonVisibility } from 'scenes/approvals/changeRequestsLogic'
import { urls } from 'scenes/urls'

import { ChangeRequest } from '~/types'

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
    const { showApproveButton, showRejectButton, showCancelButton } = getChangeRequestButtonVisibility(changeRequest)

    const handleApprove = (): void => {
        LemonDialog.open({
            title: 'Approve this change request?',
            content: (
                <div className="text-sm text-secondary">
                    This will add your approval to the change request and may automatically apply the change.
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
    }

    const handleReject = (): void => {
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
                    const reason = (document.getElementById('reject-reason') as HTMLInputElement)?.value?.trim()
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
    }

    const handleCancel = (): void => {
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
    }

    const menuItems = []
    if (showViewButton) {
        menuItems.push({
            label: 'View details',
            to: urls.approval(changeRequest.id),
        })
    }

    return (
        <div className="flex items-center gap-2">
            {showApproveButton && (
                <LemonButton type="primary" size="small" onClick={handleApprove}>
                    Approve
                </LemonButton>
            )}
            {showRejectButton && (
                <LemonButton type="secondary" size="small" onClick={handleReject}>
                    Reject
                </LemonButton>
            )}
            {showCancelButton && (
                <LemonButton type="secondary" size="small" onClick={handleCancel}>
                    Cancel
                </LemonButton>
            )}
            {menuItems.length > 0 && (
                <LemonMenu items={menuItems}>
                    <LemonButton type="secondary" size="small" icon={<IconEllipsis />} />
                </LemonMenu>
            )}
        </div>
    )
}
