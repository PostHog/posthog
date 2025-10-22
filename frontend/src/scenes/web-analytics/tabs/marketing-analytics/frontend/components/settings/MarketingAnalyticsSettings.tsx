import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AttributionSettings } from './AttributionSettings'
import { ConversionGoalsConfiguration } from './ConversionGoalsConfiguration'
import { NativeExternalDataSourceConfiguration } from './NativeExternalDataSourceConfiguration'
import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'
import { SelfManagedExternalDataSourceConfiguration } from './SelfManagedExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings({
    hideTitle = false,
    hideBaseCurrency = false,
}: {
    hideTitle?: boolean
    hideBaseCurrency?: boolean
}): JSX.Element {
    return (
        <SceneContent>
            {!hideTitle && (
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WebAnalyticsMarketing].name}
                    description={sceneConfigurations[Scene.WebAnalyticsMarketing].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.WebAnalyticsMarketing].iconType || 'default_icon_type',
                    }}
                />
            )}
            {!hideBaseCurrency && (
                <>
                    <SceneDivider />
                    <BaseCurrency />
                </>
            )}
            <SceneDivider />
            <AttributionSettings />
            <SceneDivider />
            <ConversionGoalsConfiguration />
            <SceneDivider />
            <NativeExternalDataSourceConfiguration />
            <SceneDivider />
            <NonNativeExternalDataSourceConfiguration />
            <SceneDivider />
            <SelfManagedExternalDataSourceConfiguration />
        </SceneContent>
    )
}
