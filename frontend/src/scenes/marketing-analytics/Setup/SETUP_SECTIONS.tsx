import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { LegacyOAuthReconnectBanner } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/LegacyOAuthReconnectBanner'
import { AttributionSettings } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/AttributionSettings'
import { CampaignFieldPreferencesConfiguration } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/CampaignFieldPreferencesConfiguration'
import { CampaignNameMappingsConfiguration } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/CampaignNameMappingsConfiguration'
import { ConversionGoalsConfiguration } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/ConversionGoalsConfiguration'
import { CustomSourceMappingsConfiguration } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/CustomSourceMappingsConfiguration'
import { ExternalDataSourceConfiguration } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/ExternalDataSourceConfiguration'
import { UtmAuditTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/UtmAuditTab/UtmAuditTab'
import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { SuggestedActions } from './SuggestedActions'

export interface SetupSectionDef {
    key: SetupSection
    label: string
    description: string
    content: JSX.Element
}

/** The manual half of the tab. Each entry re-hosts components that already exist —
 * `MarketingAnalyticsSettings` keeps working unchanged at
 * /settings/environment-marketing-analytics, so there are two entry points over one
 * set of components rather than a fork.
 *
 * Deliberately not carried over from the prototype's twelve sections: revenue /
 * person-join (that config belongs to Revenue analytics, not
 * `marketing_analytics_config`), funnels, audiences and data retention. Listing them
 * here with nothing behind them would be worse than leaving them out.
 */
export const SETUP_SECTIONS: SetupSectionDef[] = [
    {
        key: SetupSection.SUGGESTIONS,
        label: 'Suggested setup',
        description: '',
        content: <SuggestedActions />,
    },
    {
        key: SetupSection.SOURCES,
        label: 'Ad platforms & sources',
        description: 'Connect ad platforms and map their spend columns.',
        content: (
            <>
                <LegacyOAuthReconnectBanner />
                <ExternalDataSourceConfiguration />
            </>
        ),
    },
    {
        key: SetupSection.CONVERSION_GOALS,
        label: 'Conversion goals',
        description: 'The events that count as a conversion, and what each one is worth.',
        content: <ConversionGoalsConfiguration />,
    },
    {
        key: SetupSection.UTM_MAPPING,
        label: 'UTM & campaign mapping',
        // Until now these three were reachable only through a modal behind the
        // `advance-marketing-analytics-settings` flag, which is why UTM problems were
        // hard to fix by hand.
        description: 'Map UTM values that do not match what the ad platform reports.',
        content: (
            <div className="deprecated-space-y-6">
                <CustomSourceMappingsConfiguration />
                <CampaignNameMappingsConfiguration />
                <CampaignFieldPreferencesConfiguration />
            </div>
        ),
    },
    {
        key: SetupSection.INTEGRATION_HEALTH,
        label: 'Integration health',
        description: 'Where ad-platform campaigns and UTM tags disagree.',
        content: <UtmAuditTab />,
    },
    {
        key: SetupSection.ATTRIBUTION,
        label: 'Attribution',
        description: 'Attribution mode and lookback window.',
        content: <AttributionSettings />,
    },
    {
        key: SetupSection.GENERAL,
        label: 'General',
        description: 'Currency and other project-wide settings.',
        content: <BaseCurrency />,
    },
]
