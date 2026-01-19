import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { getApprovalActionDescription } from 'scenes/approvals/utils'

import { ChangeRequestActions } from './ChangeRequestActions'
import { ChangeRequestsLogicProps, changeRequestsLogic } from './changeRequestsLogic'

export function PendingChangeRequestBanner(props: ChangeRequestsLogicProps): JSX.Element | null {
    const logic = changeRequestsLogic(props)
    const { pendingChangeRequest, shouldShowBanner } = useValues(logic)
    const { approveRequest, rejectRequest, cancelRequest } = useActions(logic)

    if (!shouldShowBanner || !pendingChangeRequest) {
        return null
    }

    const actionDescription = getApprovalActionDescription(pendingChangeRequest.action_key)
    const requesterName = pendingChangeRequest.created_by.first_name || pendingChangeRequest.created_by.email

    return (
        <LemonBanner type="info" className="mb-4 py-4 px-2" hideIcon>
            <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                    <ProfilePicture user={pendingChangeRequest.created_by} size="lg" />
                    <div>
                        <div>
                            <strong>{requesterName}</strong>
                            {' wants to '}
                            <strong>{actionDescription}</strong>
                        </div>
                        <div className="text-muted text-xs">
                            {humanFriendlyDetailedTime(pendingChangeRequest.created_at)}
                        </div>
                    </div>
                </div>
                <ChangeRequestActions
                    changeRequest={pendingChangeRequest}
                    onApprove={approveRequest}
                    onReject={rejectRequest}
                    onCancel={cancelRequest}
                    showViewButton={true}
                />
            </div>
        </LemonBanner>
    )
}
