import { LemonBanner } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { getApprovalActionDescription } from 'scenes/approvals/utils'

import { ChangeRequest } from '~/types'

import { ChangeRequestActions, ChangeRequestActionsProps } from './ChangeRequestActions'
import { ChangeRequestsLogicProps } from './changeRequestsLogic'

export interface ChangeRequestBannerProps extends Pick<
    ChangeRequestActionsProps,
    'onApprove' | 'onReject' | 'onCancel' | 'actionInFlight'
> {
    changeRequest: ChangeRequest
    context?: ChangeRequestsLogicProps['context']
}

export function ChangeRequestBanner({
    changeRequest,
    context,
    onApprove,
    onReject,
    onCancel,
    actionInFlight,
}: ChangeRequestBannerProps): JSX.Element {
    const actionDescription = getApprovalActionDescription(changeRequest.action_key, context)
    const requesterName = changeRequest.created_by.first_name || changeRequest.created_by.email

    return (
        <LemonBanner type="info" className="mb-4 py-4 px-2" hideIcon>
            <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                    <ProfilePicture user={changeRequest.created_by} size="lg" />
                    <div>
                        <div>
                            <strong>{requesterName}</strong>
                            {' wants to '}
                            <strong>{actionDescription}</strong>
                        </div>
                        <div className="text-muted text-xs">{humanFriendlyDetailedTime(changeRequest.created_at)}</div>
                    </div>
                </div>
                <ChangeRequestActions
                    changeRequest={changeRequest}
                    onApprove={onApprove}
                    onReject={onReject}
                    onCancel={onCancel}
                    showViewButton={true}
                    actionInFlight={actionInFlight}
                />
            </div>
        </LemonBanner>
    )
}
