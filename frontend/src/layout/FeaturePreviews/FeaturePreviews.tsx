import { IconBell, IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSwitch, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useAsyncActions, useValues } from 'kea'
import { IconLink } from 'lib/lemon-ui/icons'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { useLayoutEffect, useState } from 'react'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export function FeaturePreviews({ focusedFeatureFlagKey }: { focusedFeatureFlagKey?: string }): JSX.Element {
    const { earlyAccessFeatures, rawEarlyAccessFeaturesLoading } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures } = useActions(featurePreviewsLogic)

    useLayoutEffect(() => loadEarlyAccessFeatures(), [])

    const conceptFeatures = earlyAccessFeatures.filter((f) => f.stage === 'concept')
    const disabledConceptFeatureCount = conceptFeatures.filter((f) => !f.enabled).length
    const betaFeatures = earlyAccessFeatures.filter((f) => f.stage === 'beta')

    useLayoutEffect(() => {
        if (earlyAccessFeatures.length > 0 && focusedFeatureFlagKey) {
            const element = document.getElementById(`feature-preview-${focusedFeatureFlagKey}`)
            if (element) {
                element.scrollIntoView({ behavior: 'smooth' })
            }
        }
    }, [focusedFeatureFlagKey, earlyAccessFeatures])

    return (
        <div className="flex flex-col gap-y-8">
            <div className="flex flex-col">
                <div>
                    <h3>Previews</h3>
                    <p>Get early access to these upcoming features. Let us know what you think!</p>
                    <LemonBanner type="info" className="mb-4">
                        Note that toggling these features will enable it for your account only. Each individual user in
                        your organization will need to enable it separately.
                    </LemonBanner>
                </div>
                <div className="flex flex-col flex-1 overflow-y-auto">
                    {rawEarlyAccessFeaturesLoading ? (
                        <SpinnerOverlay />
                    ) : (
                        betaFeatures.map((feature, i) => (
                            <div key={feature.flagKey} id={`feature-preview-${feature.flagKey}`}>
                                {i > 0 && <LemonDivider className="mt-3 mb-2" />}
                                <FeaturePreview feature={feature} />
                            </div>
                        ))
                    )}
                </div>
            </div>
            <div className="flex flex-col">
                <div>
                    <h3>Coming soon {disabledConceptFeatureCount > 0 && `(${disabledConceptFeatureCount})`}</h3>
                    <p>Get notified when upcoming features are ready!</p>
                </div>
                <div className="flex flex-col flex-1 overflow-y-auto">
                    {rawEarlyAccessFeaturesLoading ? (
                        <SpinnerOverlay />
                    ) : (
                        conceptFeatures.map((feature, i) => (
                            <div key={feature.flagKey} id={`feature-preview-${feature.flagKey}`}>
                                {i > 0 && <LemonDivider className="mt-3 mb-2" />}
                                <ConceptPreview feature={feature} />
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    )
}

function ConceptPreview({ feature }: { feature: EnrichedEarlyAccessFeature }): JSX.Element {
    const { updateEarlyAccessFeatureEnrollment, copyExternalFeaturePreviewLink } = useActions(featurePreviewsLogic)

    const { flagKey, enabled, name, description } = feature

    return (
        <div className="border rounded flex flex-col pl-4 pr-2 pt-2 pb-3 bg-surface-primary">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                    <h4 className="font-bold mb-0">{name}</h4>
                    <LemonButton
                        icon={<IconLink />}
                        size="small"
                        onClick={() => copyExternalFeaturePreviewLink(flagKey)}
                    />
                </div>
                <LemonButton
                    type="primary"
                    disabledReason={
                        enabled && "You have already expressed your interest. We'll contact you when it's ready"
                    }
                    onClick={() => updateEarlyAccessFeatureEnrollment(flagKey, true)}
                    size="small"
                    sideIcon={enabled ? <IconCheck /> : <IconBell />}
                >
                    {enabled ? 'Registered' : 'Get notified'}
                </LemonButton>
            </div>
            <p className="m-0">{description || <i>No description.</i>}</p>
        </div>
    )
}

function FeaturePreview({ feature }: { feature: EnrichedEarlyAccessFeature }): JSX.Element {
    const { activeFeedbackFlagKey, activeFeedbackFlagKeyLoading } = useValues(featurePreviewsLogic)
    const {
        beginEarlyAccessFeatureFeedback,
        cancelEarlyAccessFeatureFeedback,
        updateEarlyAccessFeatureEnrollment,
        copyExternalFeaturePreviewLink,
    } = useActions(featurePreviewsLogic)
    const { submitEarlyAccessFeatureFeedback } = useAsyncActions(featurePreviewsLogic)

    const { flagKey, enabled, name, description, documentationUrl } = feature
    const isFeedbackActive = activeFeedbackFlagKey === flagKey

    const [feedback, setFeedback] = useState('')

    return (
        <div className="border rounded flex flex-col pl-4 pr-2 pt-2 pb-3 bg-surface-primary">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                    <h4 className="font-bold mb-0">{name}</h4>
                    <LemonButton
                        icon={<IconLink />}
                        size="small"
                        onClick={() => copyExternalFeaturePreviewLink(flagKey)}
                    />
                </div>
                <LemonSwitch
                    checked={enabled}
                    onChange={(newChecked) => updateEarlyAccessFeatureEnrollment(flagKey, newChecked)}
                />
            </div>
            <div className="flex gap-2 justify-between">
                <p className="m-0">{description || <i>No description.</i>}</p>
                <div className="whitespace-nowrap">
                    {!isFeedbackActive && (
                        <Link onClick={() => beginEarlyAccessFeatureFeedback(flagKey)}>Give feedback</Link>
                    )}
                    {!isFeedbackActive && documentationUrl && <span>&nbsp;•&nbsp;</span>}
                    {documentationUrl && (
                        <Link to={documentationUrl} target="_blank">
                            Learn more
                        </Link>
                    )}
                </div>
            </div>
            {isFeedbackActive && (
                <div className="flex flex-col gap-2">
                    <LemonTextArea
                        autoFocus
                        placeholder={`What's your experience with ${name} been like?`}
                        className="mt-2"
                        value={feedback}
                        onChange={(value) => setFeedback(value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && e.metaKey) {
                                updateEarlyAccessFeatureEnrollment(flagKey, enabled)
                            } else if (e.key === 'Escape') {
                                cancelEarlyAccessFeatureFeedback()
                                setFeedback('')
                                e.stopPropagation() // Don't close the modal
                            }
                        }}
                    />
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                cancelEarlyAccessFeatureFeedback()
                                setFeedback('')
                            }}
                        >
                            Cancel
                        </LemonButton>

                        <LemonButton
                            type="primary"
                            onClick={() => {
                                void submitEarlyAccessFeatureFeedback(feedback).then(() => {
                                    setFeedback('')
                                })
                            }}
                            loading={activeFeedbackFlagKeyLoading}
                            className="flex-1"
                            center
                        >
                            Submit feedback
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
