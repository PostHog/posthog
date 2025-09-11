import { useActions, useAsyncActions, useValues } from 'kea'
import { useLayoutEffect, useState } from 'react'

import { IconBell, IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTextArea, Link } from '@posthog/lemon-ui'

import { BasicCard } from 'lib/components/Cards/BasicCard'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { IconLink } from 'lib/lemon-ui/icons'
import { Label } from 'lib/ui/Label/Label'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

// Feature previews can be linked to by using hash in the url
// example external link: https://app.posthog.com/settings/user-feature-previews#llm-analytics

export function FeaturePreviews(): JSX.Element {
    const { earlyAccessFeatures, rawEarlyAccessFeaturesLoading } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures } = useActions(featurePreviewsLogic)

    useLayoutEffect(() => loadEarlyAccessFeatures(), [loadEarlyAccessFeatures])

    const conceptFeatures = earlyAccessFeatures.filter((f) => f.stage === 'concept')
    const disabledConceptFeatureCount = conceptFeatures.filter((f) => !f.enabled).length
    const betaFeatures = earlyAccessFeatures.filter((f) => f.stage === 'beta')

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
                <div className="flex flex-col flex-1 gap-2 overflow-y-auto">
                    {rawEarlyAccessFeaturesLoading ? (
                        <SpinnerOverlay />
                    ) : (
                        betaFeatures.map((feature) => (
                            <div key={feature.flagKey}>
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
                <div className="flex flex-col flex-1 gap-2 overflow-y-auto">
                    {rawEarlyAccessFeaturesLoading ? (
                        <SpinnerOverlay />
                    ) : (
                        conceptFeatures.map((feature) => (
                            <div key={feature.flagKey}>
                                <ConceptPreview feature={feature} />
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    )
}

interface PreviewCardProps {
    feature: EnrichedEarlyAccessFeature
    title: React.ReactNode
    description: React.ReactNode
    actions: React.ReactNode
    children?: React.ReactNode
}

function PreviewCard({ feature, title, description, actions, children }: PreviewCardProps): JSX.Element {
    return (
        <BasicCard
            className="pl-4 pr-2 pt-2 pb-3 gap-1 @container"
            id={`${feature.flagKey}`}
            backgroundColor="var(--color-bg-surface-primary)"
        >
            <div className="flex flex-col justify-between gap-2">
                <div className="flex flex-col gap-1">
                    {title}
                    {description}
                </div>
                <div className="flex flex-col gap-2">{actions}</div>
            </div>
            {children}
        </BasicCard>
    )
}

function ConceptPreview({ feature }: { feature: EnrichedEarlyAccessFeature }): JSX.Element {
    const { updateEarlyAccessFeatureEnrollment, copyExternalFeaturePreviewLink } = useActions(featurePreviewsLogic)

    const { flagKey, enabled, name, description } = feature

    return (
        <PreviewCard
            feature={feature}
            title={
                <div className="flex items-center gap-1">
                    <h4 className="font-bold mb-0">{name}</h4>
                    <LemonButton
                        icon={<IconLink />}
                        size="xsmall"
                        onClick={() => copyExternalFeaturePreviewLink(flagKey)}
                    />
                </div>
            }
            description={
                <p className="m-0 max-w-prose">
                    {description || <span className="text-tertiary">No description</span>}
                </p>
            }
            actions={
                <div className="flex flex-col gap-2">
                    <LemonButton
                        type="primary"
                        disabledReason={
                            enabled && "You have already expressed your interest. We'll contact you when it's ready"
                        }
                        onClick={() => updateEarlyAccessFeatureEnrollment(flagKey, true, feature.stage)}
                        size="small"
                        sideIcon={enabled ? <IconCheck /> : <IconBell />}
                        className="w-fit"
                    >
                        {enabled ? 'Registered' : 'Get notified'}
                    </LemonButton>
                </div>
            }
        />
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
        <PreviewCard
            feature={feature}
            title={
                <div className="flex items-center gap-1">
                    <Label className="flex items-center gap-2 cursor-pointer" htmlFor={`${feature.flagKey}-switch`}>
                        <LemonSwitch
                            checked={enabled}
                            onChange={(newChecked) =>
                                updateEarlyAccessFeatureEnrollment(flagKey, newChecked, feature.stage)
                            }
                            id={`${feature.flagKey}-switch`}
                        />
                        <h4 className="font-bold mb-0">{name}</h4>
                    </Label>
                    <LemonButton
                        icon={<IconLink />}
                        size="xsmall"
                        onClick={() => copyExternalFeaturePreviewLink(flagKey)}
                    />
                </div>
            }
            description={
                <p className="m-0 max-w-prose">
                    {description || <span className="text-tertiary">No description</span>}
                </p>
            }
            actions={
                <div className="flex flex-col gap-2">
                    <div className="whitespace-nowrap">
                        {documentationUrl && (
                            <Link to={documentationUrl} target="_blank">
                                Learn more
                            </Link>
                        )}
                        {!isFeedbackActive && documentationUrl && <span>&nbsp;•&nbsp;</span>}
                        {!isFeedbackActive && (
                            <Link onClick={() => beginEarlyAccessFeatureFeedback(flagKey)}>Give feedback</Link>
                        )}
                    </div>
                </div>
            }
        >
            {isFeedbackActive && (
                <div className="flex flex-col gap-2 max-w-prose">
                    <LemonTextArea
                        autoFocus
                        placeholder={`What's your experience with ${name} been like?`}
                        className="mt-2"
                        value={feedback}
                        onChange={(value) => setFeedback(value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && e.metaKey) {
                                void submitEarlyAccessFeatureFeedback(feedback).then(() => {
                                    setFeedback('')
                                })
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
        </PreviewCard>
    )
}
