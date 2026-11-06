import { useActions } from 'kea'

import { IconBuilding, IconPlus } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { FeatureRequestAccountLinkApi } from '../../generated/api.schemas'
import { FeatureRequestEvidenceItem } from './FeatureRequestEvidenceItem'
import { featureRequestAccountElementId, featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestAccountItem({
    accountLink,
    canEdit,
}: {
    accountLink: FeatureRequestAccountLinkApi
    canEdit: boolean
}): JSX.Element {
    const { openNewEvidence } = useActions(featureRequestsLogic)

    return (
        <div
            id={featureRequestAccountElementId(accountLink.account.id)}
            className="flex flex-col gap-3 rounded border border-primary p-3"
        >
            <div className="flex items-center justify-between gap-2">
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
            {accountLink.evidence.length > 0 && (
                <div className="flex flex-col gap-2">
                    {accountLink.evidence.map((evidence) => (
                        <FeatureRequestEvidenceItem
                            key={evidence.id}
                            accountLink={accountLink}
                            evidence={evidence}
                            canEdit={canEdit}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
