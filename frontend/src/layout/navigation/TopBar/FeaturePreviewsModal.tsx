import { LemonButton, LemonDivider, LemonModal, LemonSwitch, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues, useAsyncActions } from 'kea'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { useEffect, useState } from 'react'
import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export function FeaturePreviewsModal(): JSX.Element {
    const { featurePreviewsModalVisible, earlyAccessFeatures, rawEarlyAccessFeaturesLoading } =
        useValues(featurePreviewsLogic)
    const { hideFeaturePreviewsModal, loadEarlyAccessFeatures } = useActions(featurePreviewsLogic)

    useEffect(() => loadEarlyAccessFeatures(), [])

    return (
        <LemonModal
            isOpen={featurePreviewsModalVisible}
            onClose={hideFeaturePreviewsModal}
            title="Feature previews"
            description="Get early access to these upcoming features. Let us know what you think!"
            width={528}
        >
            <div className="relative min-h-24">
                {earlyAccessFeatures.map((feature, i) => {
                    if (!feature.flagKey) {
                        return false
                    }
                    return (
                        <>
                            {i > 0 && <LemonDivider className="my-4" />}
                            <FeaturePreview key={feature.flagKey} feature={feature} />
                        </>
                    )
                })}
                {rawEarlyAccessFeaturesLoading && <SpinnerOverlay />}
            </div>
        </LemonModal>
    )
}

function FeaturePreview({ feature }: { feature: EnrichedEarlyAccessFeature }): JSX.Element {
    const { activeFeedbackFlagKey, activeFeedbackFlagKeyLoading } = useValues(featurePreviewsLogic)
    const { beginEarlyAccessFeatureFeedback, cancelEarlyAccessFeatureFeedback, updateEarlyAccessFeatureEnrollment } =
        useActions(featurePreviewsLogic)
    const { submitEarlyAccessFeatureFeedback } = useAsyncActions(featurePreviewsLogic)

    const { flagKey, enabled, name, description, documentationUrl } = feature
    const isFeedbackActive = activeFeedbackFlagKey === flagKey

    const [feedback, setFeedback] = useState('')

    return (
        <div>
            <div className="flex items-center justify-between">
                <h4 className="font-semibold mb-0">{name}</h4>
                <LemonSwitch
                    checked={enabled}
                    onChange={(newChecked) => updateEarlyAccessFeatureEnrollment(flagKey, newChecked)}
                />
            </div>
            <p className="my-2">{description || <i>No description.</i>}</p>
            <div>
                <Link
                    onClick={() => {
                        if (!isFeedbackActive) {
                            beginEarlyAccessFeatureFeedback(flagKey)
                        } else {
                            cancelEarlyAccessFeatureFeedback()
                            setFeedback('')
                        }
                    }}
                >
                    {!isFeedbackActive ? 'Give' : 'Cancel'} feedback
                </Link>
                {documentationUrl && (
                    <>
                        {' • '}
                        <Link to={documentationUrl} target="_blank">
                            Learn more
                        </Link>
                    </>
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
                    <LemonButton
                        type="primary"
                        onClick={async () => {
                            await submitEarlyAccessFeatureFeedback(feedback)
                            setFeedback('')
                        }}
                        loading={activeFeedbackFlagKeyLoading}
                        fullWidth
                        center
                    >
                        Submit feedback
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
