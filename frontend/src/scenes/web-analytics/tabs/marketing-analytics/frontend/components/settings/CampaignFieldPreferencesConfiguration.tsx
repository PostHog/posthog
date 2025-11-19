import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { VALID_NATIVE_MARKETING_SOURCES } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

export interface CampaignFieldPreferencesConfigurationProps {
    sourceFilter?: string
    compact?: boolean
}

export function CampaignFieldPreferencesConfiguration({
    sourceFilter,
    compact = false,
}: CampaignFieldPreferencesConfigurationProps): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCampaignFieldPreferences } = useActions(marketingAnalyticsSettingsLogic)

    const preferences = marketingAnalyticsConfig?.campaign_field_preferences || {}

    // Get integrations to display
    const integrationsToShow = sourceFilter ? [sourceFilter] : [...VALID_NATIVE_MARKETING_SOURCES]

    const updatePreference = (integration: string, matchField: 'campaign_name' | 'campaign_id'): void => {
        updateCampaignFieldPreferences({
            ...preferences,
            [integration]: {
                match_field: matchField,
            },
        })
    }

    const getMatchField = (integration: string): 'campaign_name' | 'campaign_id' => {
        return preferences[integration]?.match_field || 'campaign_name'
    }

    if (compact) {
        // Single row layout for compact mode
        const integration = integrationsToShow[0]
        return (
            <div className="flex items-center justify-between gap-4">
                <span className="text-sm font-medium">Campaign field preference</span>
                <LemonSegmentedButton
                    size="small"
                    value={getMatchField(integration)}
                    onChange={(value) => updatePreference(integration, value as 'campaign_name' | 'campaign_id')}
                    options={[
                        { value: 'campaign_name', label: 'Campaign name' },
                        { value: 'campaign_id', label: 'Campaign ID' },
                    ]}
                />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold mb-1">Campaign field preferences</h3>
                <p className="text-muted mb-4">
                    Choose whether to match <code className="text-xs">utm_campaign</code> values against campaign names
                    or campaign IDs. Defaults to campaign name if not configured.
                </p>
            </div>

            <div className="border rounded overflow-hidden">
                <table className="w-full">
                    <thead>
                        <tr className="bg-bg-light border-b">
                            {!sourceFilter && (
                                <th className="text-left text-xs font-semibold p-2 text-muted w-32">Integration</th>
                            )}
                            <th className="text-left text-xs font-semibold p-2 text-muted">Match utm_campaign by</th>
                        </tr>
                    </thead>
                    <tbody>
                        {integrationsToShow.map((integration) => (
                            <tr key={integration} className="border-b last:border-b-0">
                                {!sourceFilter && (
                                    <td className="p-2 text-sm align-middle font-medium">{integration}</td>
                                )}
                                <td className="p-2 align-middle">
                                    <LemonSegmentedButton
                                        size="small"
                                        value={getMatchField(integration)}
                                        onChange={(value) =>
                                            updatePreference(integration, value as 'campaign_name' | 'campaign_id')
                                        }
                                        options={[
                                            { value: 'campaign_name', label: 'Campaign name' },
                                            { value: 'campaign_id', label: 'Campaign ID' },
                                        ]}
                                    />
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
