import { IconImage } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { backendAssetUrl } from 'lib/utils/apiHost'
import { urls } from 'scenes/urls'

import { FeatureRequestDetailSection } from './FeatureRequestDetailSection'
import { featureRequestEvidenceSourceLabel } from './featureRequestEvidenceOptions'
import type { FeatureRequestImage } from './featureRequestsLogic'

export function FeatureRequestImages({
    images,
    onShowEvidence,
}: {
    images: FeatureRequestImage[]
    onShowEvidence: (accountId: string, evidenceId: string) => void
}): JSX.Element | null {
    if (images.length === 0) {
        return null
    }

    return (
        <FeatureRequestDetailSection icon={<IconImage />} title="Images">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {images.map(({ imageId, account, evidence }) => {
                    const evidenceName = featureRequestEvidenceSourceLabel(evidence.evidence_source)
                    const imageUrl = backendAssetUrl(`/uploaded_media/${imageId}`)

                    return (
                        <figure
                            key={`${evidence.id}-${imageId}`}
                            className="m-0 min-w-0 overflow-hidden rounded border"
                        >
                            <Link to={imageUrl} target="_blank" className="block bg-bg-light">
                                <img
                                    src={imageUrl}
                                    alt={`${account.name} - ${evidenceName}`}
                                    className="aspect-video h-full w-full object-contain"
                                />
                            </Link>
                            <figcaption className="flex min-w-0 items-center gap-1.5 border-t px-2 py-1.5 text-xs">
                                <Link to={urls.customerAnalyticsAccount(account.id)} className="truncate">
                                    {account.name}
                                </Link>
                                <span className="text-tertiary" aria-hidden>
                                    ·
                                </span>
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    onClick={() => onShowEvidence(account.id, evidence.id)}
                                    className="min-w-0 truncate"
                                    data-attr="show-feature-request-image-evidence"
                                >
                                    {evidenceName}
                                </LemonButton>
                            </figcaption>
                        </figure>
                    )
                })}
            </div>
        </FeatureRequestDetailSection>
    )
}
