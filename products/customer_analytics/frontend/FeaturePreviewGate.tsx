import { useActions, useValues } from 'kea'
import { useLayoutEffect } from 'react'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { featurePreviewsLogic } from '~/layout/FeaturePreviews/featurePreviewsLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'

export function FeaturePreviewGate(): JSX.Element {
    const { earlyAccessFeatures, rawEarlyAccessFeaturesLoading } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)

    useLayoutEffect(() => loadEarlyAccessFeatures(), [loadEarlyAccessFeatures])

    const feature = earlyAccessFeatures.find((f) => f.flagKey === FEATURE_FLAGS.CUSTOMER_ANALYTICS)

    return (
        <SceneContent>
            <ProductIntroduction
                productName="Customer analytics"
                thingName="customer analytics"
                titleOverride="Try Customer analytics"
                description="Get context about your customers. Is the number of signups going up? Are we converting free users to paid users? Need to know what are the power users of a feature? We got you covered."
                isEmpty
                actionElementOverride={
                    rawEarlyAccessFeaturesLoading ? (
                        <LemonButton type="primary" loading>
                            Loading...
                        </LemonButton>
                    ) : feature ? (
                        <label className="flex items-center gap-2 cursor-pointer" htmlFor="customer-analytics-preview">
                            <LemonSwitch
                                checked={feature.enabled}
                                onChange={(checked) =>
                                    updateEarlyAccessFeatureEnrollment(feature.flagKey, checked, feature.stage)
                                }
                                id="customer-analytics-preview"
                            />
                            <span className="font-semibold">Enable feature preview</span>
                        </label>
                    ) : (
                        <LemonButton type="primary" to={urls.settings('user-feature-previews')}>
                            Open feature previews
                        </LemonButton>
                    )
                }
                docsURL="https://posthog.com/docs/customer-analytics"
            />
        </SceneContent>
    )
}
