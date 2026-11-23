import { Collapsible, CollapsibleContent, CollapsibleTrigger, Separator } from '@posthog/quill'

import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

import { ConversionActionsSettings } from 'products/marketing_analytics/frontend/recommendations/ConversionActionsSettings'

import { LegacyOAuthReconnectBanner } from '../LegacyOAuthReconnectBanner'
import { AttributionSettings } from './AttributionSettings'
import { ConversionGoalsConfiguration } from './ConversionGoalsConfiguration'
import { ExternalDataSourceConfiguration } from './ExternalDataSourceConfiguration'
import { MarketingIntegrationAdvancedSettings } from './MarketingIntegrationAdvancedSettings'

export function QuillMarketingAnalyticsSettings({ hideBaseCurrency }: { hideBaseCurrency: boolean }): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            <LegacyOAuthReconnectBanner />
            <ExternalDataSourceConfiguration />
            <Separator />
            <ConversionGoalsConfiguration />
            <Separator />
            <AttributionSettings />
            <FlaggedFeature flag={FEATURE_FLAGS.MARKETING_ANALYTICS_RECOMMENDATION_CONVERSION_ACTIONS}>
                <>
                    <Separator />
                    <ConversionActionsSettings />
                </>
            </FlaggedFeature>
            {!hideBaseCurrency && (
                <>
                    <Separator />
                    <BaseCurrency />
                </>
            )}
            <FlaggedFeature flag="advance-marketing-analytics-settings">
                <>
                    <Separator />
                    <Collapsible variant="folder">
                        <CollapsibleTrigger>Advanced marketing settings</CollapsibleTrigger>
                        <CollapsibleContent className="pt-2">
                            <MarketingIntegrationAdvancedSettings />
                        </CollapsibleContent>
                    </Collapsible>
                </>
            </FlaggedFeature>
        </div>
    )
}
