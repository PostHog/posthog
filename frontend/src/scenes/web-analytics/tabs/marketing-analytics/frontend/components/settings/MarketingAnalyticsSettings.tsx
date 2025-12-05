import { LemonCollapse } from '@posthog/lemon-ui'

import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AttributionSettings } from './AttributionSettings'
import { ConversionGoalsConfiguration } from './ConversionGoalsConfiguration'
import { ExternalDataSourceConfiguration } from './ExternalDataSourceConfiguration'
import { MarketingIntegrationAdvancedSettings } from './MarketingIntegrationAdvancedSettings'

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
            <ExternalDataSourceConfiguration />
            <SceneDivider />
            <ConversionGoalsConfiguration />
            <SceneDivider />
            <AttributionSettings />
            <SceneDivider />
            {!hideBaseCurrency && (
                <>
                    <SceneDivider />
                    <BaseCurrency />
                </>
            )}
            <FlaggedFeature flag="advance-marketing-analytics-settings">
                <>
                    <SceneDivider />
                    <LemonCollapse
                        panels={[
                            {
                                key: 'advanced-marketing-settings',
                                header: 'Advanced marketing settings',
                                content: <MarketingIntegrationAdvancedSettings />,
                            },
                        ]}
                    />
                </>
            </FlaggedFeature>
        </SceneContent>
    )
}
