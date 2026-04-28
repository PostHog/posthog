import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { SceneExport } from '~/scenes/sceneTypes'

import { customerAnalyticsFeaturePreviewGate } from '../../featurePreviewGate'
import { JourneyTemplatePicker } from './JourneyTemplatePicker'
import { journeyTemplatePickerLogic } from './journeyTemplatePickerLogic'

export const scene: SceneExport = {
    component: CustomerJourneyTemplatesScene,
    logic: journeyTemplatePickerLogic,
    productKey: ProductKey.CUSTOMER_ANALYTICS,
}

export function CustomerJourneyTemplatesScene(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={customerAnalyticsFeaturePreviewGate}>
            <SceneContent>
                <div className="flex items-center justify-start mb-4">
                    <LemonButton type="tertiary" size="small" to={urls.customerAnalyticsJourneys()}>
                        ← Back to journeys
                    </LemonButton>
                </div>
                <JourneyTemplatePicker />
            </SceneContent>
        </FeaturePreviewSceneGate>
    )
}
