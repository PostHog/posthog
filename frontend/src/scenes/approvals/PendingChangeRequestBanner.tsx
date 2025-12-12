import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils'
import { getApprovalActionDescription } from 'scenes/approvals/utils'

import { ChangeRequestActions } from './ChangeRequestActions'
import { PendingChangeRequestLogicProps, pendingChangeRequestLogic } from './pendingChangeRequestLogic'

export function PendingChangeRequestBanner(props: PendingChangeRequestLogicProps): JSX.Element | null {
    const logic = pendingChangeRequestLogic(props)
    const { pendingChangeRequest, shouldShowBanner } = useValues(logic)
    const { approveRequest, rejectRequest, cancelRequest } = useActions(logic)

    if (!shouldShowBanner || !pendingChangeRequest) {
        return null
    }

    const isRequester = pendingChangeRequest.is_requester
    const userDecision = pendingChangeRequest.user_decision

    const actionDescription = getApprovalActionDescription(pendingChangeRequest.action_key)
    const requesterName = pendingChangeRequest.created_by.first_name || pendingChangeRequest.created_by.email

    let message: string
    if (isRequester && !pendingChangeRequest.can_approve) {
        message = `Your request to ${actionDescription} is pending approval.`
    } else if (pendingChangeRequest.can_approve) {
        message = `There is a pending request to ${actionDescription}.`
    } else {
        message = `This resource has a pending approval request and cannot be edited until the request is resolved.`
    }

    return (
        <LemonBanner type="info" className="mb-4">
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <strong>
                        {isRequester
                            ? '⏳ Awaiting approval'
                            : pendingChangeRequest.can_approve
                              ? '🔒 Pending approval request'
                              : '🔒 Pending approval request'}
                    </strong>
                </div>
                <div>
                    {message}
                    {!isRequester && (
                        <>
                            {' '}
                            <span className="text-muted">
                                Requested by {requesterName} •{' '}
                                {humanFriendlyDetailedTime(pendingChangeRequest.created_at)}
                            </span>
                        </>
                    )}
                </div>
                {pendingChangeRequest.approvals && (
                    <div className="text-muted">
                        Approvals: {pendingChangeRequest.approvals.length}/{pendingChangeRequest.policy_snapshot.quorum}
                    </div>
                )}
                {userDecision && (
                    <div className="text-muted">
                        You have {userDecision === 'approved' ? 'approved' : 'rejected'} this request.
                    </div>
                )}
                <div className="flex gap-2">
                    <ChangeRequestActions
                        changeRequest={pendingChangeRequest}
                        onApprove={approveRequest}
                        onReject={rejectRequest}
                        onCancel={cancelRequest}
                        showViewButton={true}
                    />
                </div>
            </div>
        </LemonBanner>
    )
}
