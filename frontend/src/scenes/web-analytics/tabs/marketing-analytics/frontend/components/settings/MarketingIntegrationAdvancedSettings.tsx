import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { externalDataSources } from '~/queries/schema/schema-general'

import { getEnabledNativeMarketingSources } from '../../logic/utils'
import { IntegrationSettingsCard } from './IntegrationSettingsCard'

export function MarketingIntegrationAdvancedSettings(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const enabledSources = getEnabledNativeMarketingSources(featureFlags)
    const availableIntegrations = externalDataSources.filter((source) => enabledSources.includes(source as any))

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold mb-1">Integration-specific settings</h3>
                <p className="text-muted mb-4">
                    Configure campaign name mappings, custom UTM source mappings, and field preferences for each ad
                    platform integration.
                </p>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                {availableIntegrations.map((integration) => (
                    <IntegrationSettingsCard key={integration} integrationName={integration} />
                ))}
            </div>
        </div>
    )
}
