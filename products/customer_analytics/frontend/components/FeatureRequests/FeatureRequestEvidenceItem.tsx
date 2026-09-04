import { useActions } from 'kea'

import { IconImage, IconPencil } from '@posthog/icons'
import { LemonButton, LemonCard, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { FeatureRequestAccountLinkApi, FeatureRequestEvidenceApi } from '../../generated/api.schemas'
import { featureRequestEvidenceSourceLabel } from './featureRequestEvidenceOptions'
import { featureRequestEvidenceElementId, featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestEvidenceItem({
    accountLink,
    evidence,
    canEdit,
}: {
    accountLink: FeatureRequestAccountLinkApi
    evidence: FeatureRequestEvidenceApi
    canEdit: boolean
}): JSX.Element {
    const { openEditEvidence } = useActions(featureRequestsLogic)

    return (
        <div id={featureRequestEvidenceElementId(evidence.id)}>
            <LemonCard hoverEffect={false} className="p-3 shadow-none">
                <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-tertiary">
                            <span>{featureRequestEvidenceSourceLabel(evidence.evidence_source)}</span>
                            {evidence.requested_on && <span>{evidence.requested_on}</span>}
                            {evidence.image_ids.length > 0 && (
                                <IconImage className="size-3.5" aria-label="Contains images" />
                            )}
                            {evidence.source_url && (
                                <Link to={evidence.source_url} target="_blank">
                                    Open source
                                </Link>
                            )}
                        </div>
                        {evidence.summary && (
                            <p className="m-0 whitespace-pre-wrap text-secondary">{evidence.summary}</p>
                        )}
                        {evidence.customer_quote && (
                            <blockquote className="m-0 border-l-2 pl-3 text-secondary whitespace-pre-wrap">
                                {evidence.customer_quote}
                            </blockquote>
                        )}
                        <span className="text-xs text-tertiary">
                            Added <TZLabel time={evidence.created_at} />
                        </span>
                    </div>
                    {canEdit && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconPencil />}
                            onClick={() => openEditEvidence(accountLink, evidence)}
                            aria-label="Edit evidence"
                        />
                    )}
                </div>
            </LemonCard>
        </div>
    )
}
