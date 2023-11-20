import { LemonButton, LemonDivider, LemonModal, LemonSwitch, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues, useAsyncActions } from 'kea'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { useLayoutEffect, useState } from 'react'
import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'
import clsx from 'clsx'

export function FeaturePreviewsModal({
    inline,
}: {
    /** @deprecated This is only for Storybook. */
    inline?: boolean
}): JSX.Element {
    const { featurePreviewsModalVisible, earlyAccessFeatures, rawEarlyAccessFeaturesLoading } =
        useValues(featurePreviewsLogic)
    const { hideFeaturePreviewsModal, loadEarlyAccessFeatures } = useActions(featurePreviewsLogic)

    useLayoutEffect(() => loadEarlyAccessFeatures(), [])

    return (
        <LemonModal
            isOpen={inline || featurePreviewsModalVisible}
            onClose={hideFeaturePreviewsModal}
            title="Feature previews"
            description="Get early access to these upcoming features. Let us know what you think!"
            width={528}
            inline={inline}
        >
            <div
                className={clsx(
                    'flex flex-col relative min-h-24',
                    earlyAccessFeatures.length === 0 && 'items-center justify-center'
                )}
            >
                {earlyAccessFeatures.map((feature, i) => {
                    if (!feature.flagKey) {
                        return false
                    }
                    return (
                        <div key={feature.flagKey}>
                            {i > 0 && <LemonDivider className="my-4" />}
                            <FeaturePreview key={feature.flagKey} feature={feature} />
                        </div>
                    )
                })}
                {rawEarlyAccessFeaturesLoading ? (
                    <SpinnerOverlay />
                ) : earlyAccessFeatures.length === 0 ? (
                    <i className="text-center">
                        No feature previews currently available.
                        <br />
                        Check back later!
                    </i>
                ) : null}
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
                        onClick={() => {
                            void submitEarlyAccessFeatureFeedback(feedback).then(() => {
                                setFeedback('')
                            })
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
