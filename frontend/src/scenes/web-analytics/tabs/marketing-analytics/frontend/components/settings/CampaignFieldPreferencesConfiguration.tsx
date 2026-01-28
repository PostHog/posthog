import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { CampaignFieldPreference, MatchField } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { getEnabledNativeMarketingSources } from '../../logic/utils'

export interface CampaignFieldPreferencesConfigurationProps {
    sourceFilter?: string
}

const DEFAULT_MATCH_FIELD: CampaignFieldPreference['match_field'] = MatchField.CAMPAIGN_NAME

export function CampaignFieldPreferencesConfiguration({
    sourceFilter,
}: CampaignFieldPreferencesConfigurationProps): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCampaignFieldPreferences } = useActions(marketingAnalyticsSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const preferences = marketingAnalyticsConfig?.campaign_field_preferences || {}

    const enabledSources = getEnabledNativeMarketingSources(featureFlags)
    const integrationsToShow = sourceFilter ? [sourceFilter] : [...enabledSources]

    const updatePreference = (integration: string, matchField: CampaignFieldPreference['match_field']): void => {
        updateCampaignFieldPreferences({
            ...preferences,
            [integration]: {
                match_field: matchField,
            },
        })
    }

    const getMatchField = (integration: string): CampaignFieldPreference['match_field'] => {
        return preferences[integration]?.match_field || DEFAULT_MATCH_FIELD
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
                                            updatePreference(
                                                integration,
                                                value as CampaignFieldPreference['match_field']
                                            )
                                        }
                                        options={[
                                            { value: MatchField.CAMPAIGN_NAME, label: 'Campaign name' },
                                            { value: MatchField.CAMPAIGN_ID, label: 'Campaign ID' },
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
