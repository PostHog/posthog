import clsx from 'clsx'
import { useActions, useAsyncActions, useValues } from 'kea'
import { useLayoutEffect, useState } from 'react'

import { IconBell, IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSwitch, LemonTabs, LemonTextArea, Link } from '@posthog/lemon-ui'

import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { IconLink } from 'lib/lemon-ui/icons'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export function FeaturePreviews({ focusedFeatureFlagKey }: { focusedFeatureFlagKey?: string }): JSX.Element {
    const [activeKey, setActiveKey] = useState<'beta' | 'concept'>('beta')
    const { earlyAccessFeatures, rawEarlyAccessFeaturesLoading } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures } = useActions(featurePreviewsLogic)

    useLayoutEffect(() => loadEarlyAccessFeatures(), [])

    const conceptFeatures = earlyAccessFeatures.filter((f) => f.stage === 'concept')
    const disabledConceptFeatureCount = conceptFeatures.filter((f) => !f.enabled).length
    const betaFeatures = earlyAccessFeatures.filter((f) => f.stage === 'beta')

    useLayoutEffect(() => {
        if (focusedFeatureFlagKey && conceptFeatures.some((f) => f.flagKey === focusedFeatureFlagKey)) {
            setActiveKey('concept')
        }
    }, [focusedFeatureFlagKey, conceptFeatures])

    useLayoutEffect(() => {
        if (earlyAccessFeatures.length > 0 && focusedFeatureFlagKey) {
            const element = document.getElementById(`feature-preview-${focusedFeatureFlagKey}`)
            if (element) {
                element.scrollIntoView({ behavior: 'smooth' })
            }
        }
    }, [focusedFeatureFlagKey, earlyAccessFeatures])

    return (
        <div
            className={clsx(
                'relative flex min-h-24 flex-col overflow-y-auto px-1',
                earlyAccessFeatures.length === 0 && 'items-center justify-center'
            )}
        >
            <LemonTabs
                activeKey={activeKey}
                onChange={setActiveKey}
                size="small"
                tabs={[
                    {
                        key: 'beta',
                        label: <div className="px-2">Previews</div>,
                        content: (
                            <div className="flex flex-1 flex-col overflow-y-auto p-2">
                                <LemonBanner type="info" className="mb-2">
                                    Get early access to these upcoming features. Let us know what you think!
                                </LemonBanner>
                                <LemonBanner type="info" className="mb-2">
                                    Note that toggling these features will enable it for your account only. Each
                                    individual user in your organization will need to enable it separately.
                                </LemonBanner>
                                {betaFeatures.map((feature, i) => (
                                    <div key={feature.flagKey} id={`feature-preview-${feature.flagKey}`}>
                                        {i > 0 && <LemonDivider className="mb-2 mt-3" />}
                                        <FeaturePreview feature={feature} />
                                    </div>
                                ))}
                            </div>
                        ),
                    },
                    {
                        key: 'concept',
                        label: (
                            <div className="px-2">
                                {/* eslint-disable-next-line react-google-translate/no-conditional-text-nodes-with-siblings */}
                                Coming soon {disabledConceptFeatureCount > 0 && `(${disabledConceptFeatureCount})`}
                            </div>
                        ),
                        content: (
                            <div className="flex flex-1 flex-col overflow-y-auto p-2">
                                <LemonBanner type="info" className="mb-2">
                                    Get notified when upcoming features are ready!
                                </LemonBanner>
                                {conceptFeatures.map((feature, i) => (
                                    <div key={feature.flagKey} id={`feature-preview-${feature.flagKey}`}>
                                        {i > 0 && <LemonDivider className="mb-2 mt-3" />}
                                        <ConceptPreview feature={feature} />
                                    </div>
                                ))}
                            </div>
                        ),
                    },
                ]}
            />
            {rawEarlyAccessFeaturesLoading ? (
                <SpinnerOverlay />
            ) : earlyAccessFeatures.length === 0 ? (
                <i className="mt-2 text-center">
                    No feature previews currently available.
                    <br />
                    Check back later!
                </i>
            ) : null}
        </div>
    )
}

function ConceptPreview({ feature }: { feature: EnrichedEarlyAccessFeature }): JSX.Element {
    const { updateEarlyAccessFeatureEnrollment, copyExternalFeaturePreviewLink } = useActions(featurePreviewsLogic)

    const { flagKey, enabled, name, description } = feature

    return (
        <div>
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                    <h4 className="mb-0 font-semibold">{name}</h4>
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
            <p className="mb-1">{description || <i>No description.</i>}</p>
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
        <div>
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                    <h4 className="mb-0 font-semibold">{name}</h4>
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
            <p className="my-2">{description || <i>No description.</i>}</p>
            <div>
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
