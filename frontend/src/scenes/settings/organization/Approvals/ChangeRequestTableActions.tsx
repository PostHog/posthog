import { LemonButton } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { changeRequestDialogHandlers } from 'scenes/approvals/ChangeRequestActions'
import { getChangeRequestButtonVisibility } from 'scenes/approvals/changeRequestsLogic'
import { urls } from 'scenes/urls'

import { ChangeRequest } from '~/types'

export interface ChangeRequestTableActionsProps {
    changeRequest: ChangeRequest
    onApprove: (id: string) => void
    onReject: (id: string, reason: string) => void
}

export function ChangeRequestTableActions({
    changeRequest,
    onApprove,
    onReject,
}: ChangeRequestTableActionsProps): JSX.Element {
    const { showApproveButton, showRejectButton } = getChangeRequestButtonVisibility(changeRequest)
    const { handleApprove, handleReject } = changeRequestDialogHandlers({ changeRequest, onApprove, onReject })

    return (
        <More
            overlay={
                <>
                    <LemonButton fullWidth to={urls.approval(changeRequest.id)}>
                        View details
                    </LemonButton>
                    {showApproveButton && (
                        <LemonButton fullWidth type="primary" onClick={handleApprove}>
                            Approve
                        </LemonButton>
                    )}
                    {showRejectButton && (
                        <LemonButton fullWidth status="danger" onClick={handleReject}>
                            Reject
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
