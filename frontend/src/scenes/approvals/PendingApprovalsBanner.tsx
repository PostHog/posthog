import { useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { pendingApprovalsLogic } from './pendingApprovalsLogic'

export function PendingApprovalsBanner(): JSX.Element | null {
    const { actionableCount, pendingChangeRequestsLoading } = useValues(pendingApprovalsLogic)

    if (pendingChangeRequestsLoading || actionableCount === 0) {
        return null
    }

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
            {actionableCount} {pluralize(actionableCount, 'change request', 'change requests', false)}{' '}
            {actionableCount === 1 ? 'is' : 'are'} awaiting your decision
        </LemonBanner>
    )
}
