import { useActions, useValues } from 'kea'
import { useLayoutEffect } from 'react'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from '~/layout/FeaturePreviews/featurePreviewsLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'

export function FeaturePreviewGate(): JSX.Element {
    const { earlyAccessFeatures, rawEarlyAccessFeaturesLoading } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)

    useLayoutEffect(() => loadEarlyAccessFeatures(), [loadEarlyAccessFeatures])

    const feature: EnrichedEarlyAccessFeature | undefined = earlyAccessFeatures.find(
        (f) => f.flagKey === FEATURE_FLAGS.CUSTOMER_ANALYTICS
    )

    return (
        <SceneContent>
            <div className="flex flex-col items-center justify-center min-h-[60vh]">
                <div className="max-w-lg w-full space-y-4 text-center">
                    <h2>Customer analytics</h2>
                    <p className="text-secondary">
                        Customer analytics is currently in beta. Enable the feature preview to get started.
                    </p>
                    {rawEarlyAccessFeaturesLoading ? (
                        <div className="relative h-20">
                            <SpinnerOverlay />
                        </div>
                    ) : feature ? (
                        <FeaturePreviewCard feature={feature} onToggle={updateEarlyAccessFeatureEnrollment} />
                    ) : (
                        <p className="text-secondary">
                            You can enable it in{' '}
                            <Link to={urls.settings('user-feature-previews')}>feature preview settings</Link>.
                        </p>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}

function FeaturePreviewCard({
    feature,
    onToggle,
}: {
    feature: EnrichedEarlyAccessFeature
    onToggle: (flagKey: string, enabled: boolean, stage?: string) => void
}): JSX.Element {
    return (
        <div className="border rounded-lg p-4 text-left bg-surface-primary">
            <label className="flex items-center gap-2 cursor-pointer mb-2" htmlFor="customer-analytics-preview-switch">
                <LemonSwitch
                    checked={feature.enabled}
                    onChange={(checked) => onToggle(feature.flagKey, checked, feature.stage)}
                    id="customer-analytics-preview-switch"
                />
                <span className="font-bold">{feature.name}</span>
            </label>
            {feature.description && <p className="text-secondary m-0">{feature.description}</p>}
            {feature.documentationUrl && (
                <Link to={feature.documentationUrl} target="_blank" className="mt-2 inline-block">
                    Learn more
                </Link>
            )}
        </div>
    )
}
