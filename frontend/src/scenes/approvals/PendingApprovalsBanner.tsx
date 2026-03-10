import { useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { pendingApprovalsLogic } from './pendingApprovalsLogic'

export function PendingApprovalsBanner(): JSX.Element | null {
    const { actionableCount, pendingCount, pendingChangeRequestsLoading } = useValues(pendingApprovalsLogic)

    if (pendingChangeRequestsLoading || pendingCount === 0) {
        return null
    }

    const message =
        actionableCount > 0
            ? `${actionableCount} ${pluralize(actionableCount, 'change request', 'change requests', false)} ${actionableCount === 1 ? 'is' : 'are'} awaiting your decision`
            : `${pendingCount} ${pluralize(pendingCount, 'change request', 'change requests', false)} ${pendingCount === 1 ? 'is' : 'are'} pending approval`

    return (
        <LemonBanner
            type="info"
            className="mb-4"
            action={
                <LemonButton type="secondary" size="small" to={urls.approvals()}>
                    Go to change requests
                </LemonButton>
            }
        >
            {message}
        </LemonBanner>
    )
}
