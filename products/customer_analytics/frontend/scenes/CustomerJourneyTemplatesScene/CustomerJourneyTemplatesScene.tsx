import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { SceneExport } from '~/scenes/sceneTypes'

import { FeaturePreviewGate } from '../../FeaturePreviewGate'
import { JourneyTemplatePicker } from './JourneyTemplatePicker'
import { journeyTemplatePickerLogic } from './journeyTemplatePickerLogic'

export const scene: SceneExport = {
    component: CustomerJourneyTemplatesScene,
    logic: journeyTemplatePickerLogic,
    productKey: ProductKey.CUSTOMER_ANALYTICS,
}

export function CustomerJourneyTemplatesScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]) {
        return <FeaturePreviewGate />
    }

    return (
        <SceneContent>
            <div className="flex items-center justify-start mb-4">
                <LemonButton type="tertiary" size="small" to={urls.customerAnalyticsJourneys()}>
                    ← Back to journeys
                </LemonButton>
            </div>
            <JourneyTemplatePicker />
        </SceneContent>
    )
}
