import { LemonCollapse } from '@posthog/lemon-ui'

import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ConversionActionsSettings } from 'products/marketing_analytics/frontend/recommendations/ConversionActionsSettings'

import { LegacyOAuthReconnectBanner } from '../LegacyOAuthReconnectBanner'
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
                    name={sceneConfigurations[Scene.MarketingAnalyticsSettings].name}
                    description={sceneConfigurations[Scene.MarketingAnalyticsSettings].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.MarketingAnalyticsSettings].iconType || 'default_icon_type',
                    }}
                />
            )}
            <LegacyOAuthReconnectBanner />
            <ExternalDataSourceConfiguration />
            <SceneDivider />
            <ConversionGoalsConfiguration />
            <SceneDivider />
            <AttributionSettings />
            <SceneDivider />
            <FlaggedFeature flag={FEATURE_FLAGS.MARKETING_ANALYTICS_RECOMMENDATION_CONVERSION_ACTIONS}>
                <>
                    <ConversionActionsSettings />
                    <SceneDivider />
                </>
            </FlaggedFeature>
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
