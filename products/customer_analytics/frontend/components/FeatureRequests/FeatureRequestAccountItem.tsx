import { useActions } from 'kea'

import { IconBuilding, IconPlus } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { FeatureRequestAccountLinkApi } from '../../generated/api.schemas'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestAccountItem({
    accountLink,
    canEdit,
}: {
    accountLink: FeatureRequestAccountLinkApi
    canEdit: boolean
}): JSX.Element {
    const { openNewEvidence } = useActions(featureRequestsLogic)

    return (
        <div className="flex items-center justify-between gap-2 rounded border border-primary p-3">
            <Link
                to={urls.customerAnalyticsAccount(accountLink.account.id)}
                className="flex min-w-0 items-center gap-2 font-medium"
            >
                <IconBuilding className="size-4 shrink-0" />
                <span className="truncate">{accountLink.account.name}</span>
            </Link>
            {canEdit && (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconPlus />}
                    onClick={() => openNewEvidence(accountLink)}
                    data-attr="add-feature-request-evidence"
                >
                    Add evidence
                </LemonButton>
            )}
        </div>
    )
}
