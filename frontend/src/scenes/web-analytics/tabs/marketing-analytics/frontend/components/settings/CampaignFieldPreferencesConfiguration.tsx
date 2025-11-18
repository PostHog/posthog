import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { externalDataSources } from '~/queries/schema/schema-general'
import { CampaignFieldPreference } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { VALID_NATIVE_MARKETING_SOURCES } from '../../logic/utils'

export function CampaignFieldPreferencesConfiguration(): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCampaignFieldPreferences } = useActions(marketingAnalyticsSettingsLogic)

    const preferences = marketingAnalyticsConfig?.campaign_field_preferences || {}
    const [selectedIntegration, setSelectedIntegration] = useState<string>('')
    const [matchField, setMatchField] = useState<'campaign_name' | 'campaign_id'>('campaign_name')

    const availableIntegrations = externalDataSources.filter((source) =>
        VALID_NATIVE_MARKETING_SOURCES.includes(source as any)
    )

    const updatePreferences = (newPreferences: Record<string, CampaignFieldPreference>): void => {
        updateCampaignFieldPreferences(newPreferences)
    }

    const addPreference = (): void => {
        if (!selectedIntegration) {
            return
        }

        updatePreferences({
            ...preferences,
            [selectedIntegration]: {
                match_field: matchField,
            },
        })

        // Reset form
        setSelectedIntegration('')
        setMatchField('campaign_name')
    }

    const removePreference = (integration: string): void => {
        const newPreferences = { ...preferences }
        delete newPreferences[integration]
        updatePreferences(newPreferences)
    }

    const totalPreferences = Object.keys(preferences).length

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold mb-1">Campaign field preferences</h3>
                <p className="text-muted mb-4">
                    Configure which field to match <code className="text-xs">utm_campaign</code> values against for each
                    ad platform integration. Choose between campaign name (descriptive text) or campaign ID (platform
                    identifier).
                </p>
                <p className="text-muted-alt text-xs mb-4">
                    <strong>Note:</strong> Manual mappings (configured above) always take precedence over automatic
                    field matching. If no preference is set for an integration, it defaults to matching by campaign
                    name.
                </p>
            </div>

            {totalPreferences > 0 && (
                <div className="border rounded p-4 space-y-4">
                    <h4 className="font-semibold">Current preferences ({totalPreferences})</h4>
                    <div className="space-y-3">
                        {Object.entries(preferences).map(([integration, pref]) => (
                            <div
                                key={integration}
                                className="flex items-center justify-between bg-bg-light rounded p-3"
                            >
                                <div className="space-y-1">
                                    <div className="font-medium">{integration}</div>
                                    <div className="text-sm text-muted">
                                        Match: <span className="font-mono text-xs">{pref.match_field}</span>
                                    </div>
                                </div>
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    icon={<IconTrash />}
                                    onClick={() => removePreference(integration)}
                                    tooltip="Remove preference"
                                />
                            </div>
                        ))}
                    </div>
                </div>
            )}

            <div className="border rounded p-4 space-y-3">
                <h4 className="font-semibold">Add field preference</h4>

                <div className="space-y-3">
                    <div>
                        <label className="block text-sm font-medium mb-1">Integration</label>
                        <LemonSelect
                            value={selectedIntegration}
                            onChange={setSelectedIntegration}
                            options={[
                                { label: 'Select an integration...', value: '' },
                                ...availableIntegrations.map((integration) => ({
                                    label: integration,
                                    value: integration,
                                    disabledReason: preferences[integration]
                                        ? 'Preference already configured'
                                        : undefined,
                                })),
                            ]}
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            The ad platform integration to configure field matching for
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">Match field</label>
                        <LemonSelect
                            value={matchField}
                            onChange={setMatchField}
                            options={[
                                {
                                    label: 'Campaign name',
                                    value: 'campaign_name',
                                },
                                {
                                    label: 'Campaign ID',
                                    value: 'campaign_id',
                                },
                            ]}
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            The field to match <code className="text-xs">utm_campaign</code> values against
                        </div>
                    </div>

                    <LemonButton type="primary" onClick={addPreference} disabled={!selectedIntegration} fullWidth>
                        Add preference
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
