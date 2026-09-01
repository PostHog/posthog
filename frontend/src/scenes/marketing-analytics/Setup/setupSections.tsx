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

import { SECTION_LABEL } from './sectionRouting'
import { SuggestedActions } from './SuggestedActions'

export interface SetupSectionDef {
    key: SetupSection
    label: string
    description: string
    content: JSX.Element
}

/** The manual half of the tab. Each entry re-hosts existing components, so this and
 * /settings/environment-marketing-analytics are two entry points over one set of
 * components rather than a fork. */
export const SETUP_SECTIONS: SetupSectionDef[] = [
    {
        key: SetupSection.SUGGESTIONS,
        label: SECTION_LABEL[SetupSection.SUGGESTIONS],
        description: '',
        content: <SuggestedActions />,
    },
    {
        key: SetupSection.SOURCES,
        label: SECTION_LABEL[SetupSection.SOURCES],
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
        label: SECTION_LABEL[SetupSection.CONVERSION_GOALS],
        description: 'The events that count as a conversion, and what each one is worth.',
        content: <ConversionGoalsConfiguration />,
    },
    {
        key: SetupSection.UTM_MAPPING,
        label: SECTION_LABEL[SetupSection.UTM_MAPPING],
        // Reachable until now only through a modal behind the
        // `advance-marketing-analytics-settings` flag.
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
        label: SECTION_LABEL[SetupSection.INTEGRATION_HEALTH],
        description: 'Where ad-platform campaigns and UTM tags disagree.',
        content: <UtmAuditTab />,
    },
    {
        key: SetupSection.ATTRIBUTION,
        label: SECTION_LABEL[SetupSection.ATTRIBUTION],
        description: 'Attribution mode and lookback window.',
        content: <AttributionSettings />,
    },
    {
        key: SetupSection.GENERAL,
        label: SECTION_LABEL[SetupSection.GENERAL],
        description: 'Currency and other project-wide settings.',
        content: <BaseCurrency />,
    },
]
