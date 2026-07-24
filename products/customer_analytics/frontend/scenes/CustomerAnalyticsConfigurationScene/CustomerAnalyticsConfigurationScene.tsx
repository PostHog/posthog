import { SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

import { customerAnalyticsFeaturePreviewGate } from '../../featurePreviewGate'
import { CUSTOMER_ANALYTICS_LOGIC_KEY } from '../../utils'
import { customerAnalyticsConfigurationSceneLogic } from './customerAnalyticsConfigurationSceneLogic'

export const scene: SceneExport = {
    component: CustomerAnalyticsConfigurationScene,
    logic: customerAnalyticsConfigurationSceneLogic,
    paramsToProps: ({ searchParams: { tab } }) => ({ initialTab: tab }),
}

export function CustomerAnalyticsConfigurationScene(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={customerAnalyticsFeaturePreviewGate}>
            <div className="mb-2 -ml-[var(--button-padding-x-lg)]">
                <SceneBreadcrumbBackButton />
            </div>
            <Settings
                logicKey={CUSTOMER_ANALYTICS_LOGIC_KEY}
                sectionId="environment-customer-analytics"
                handleLocally
            />
        </FeaturePreviewSceneGate>
    )
}
