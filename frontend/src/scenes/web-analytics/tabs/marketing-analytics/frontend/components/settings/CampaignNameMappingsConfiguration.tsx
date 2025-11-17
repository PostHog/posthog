import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { externalDataSources } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { VALID_NATIVE_MARKETING_SOURCES } from '../../logic/utils'

const SEPARATOR = ','

export function CampaignNameMappingsConfiguration(): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCampaignNameMappings } = useActions(marketingAnalyticsSettingsLogic)

    const campaignMappings = marketingAnalyticsConfig?.campaign_name_mappings || {}
    const [selectedSource, setSelectedSource] = useState<string>('')
    const [newCleanName, setNewCleanName] = useState('')
    const [newRawValues, setNewRawValues] = useState('')

    const availableSources = externalDataSources.filter((source) =>
        VALID_NATIVE_MARKETING_SOURCES.includes(source as any)
    )

    const updateMappings = (newMappings: Record<string, Record<string, string[]>>): void => {
        updateCampaignNameMappings(newMappings)
    }

    const addMapping = (): void => {
        if (!selectedSource || !newCleanName.trim() || !newRawValues.trim()) {
            return
        }

        const rawValuesArray = newRawValues
            .split(SEPARATOR)
            .map((v) => v.trim())
            .filter((v) => v.length > 0)

        const sourceMappings = campaignMappings[selectedSource] || {}

        updateMappings({
            ...campaignMappings,
            [selectedSource]: {
                ...sourceMappings,
                [newCleanName.trim()]: rawValuesArray,
            },
        })

        setNewCleanName('')
        setNewRawValues('')
    }

    const removeMapping = (source: string, cleanName: string): void => {
        const sourceMappings = { ...campaignMappings[source] }
        delete sourceMappings[cleanName]

        if (Object.keys(sourceMappings).length === 0) {
            const newMappings = { ...campaignMappings }
            delete newMappings[source]
            updateMappings(newMappings)
        } else {
            updateMappings({
                ...campaignMappings,
                [source]: sourceMappings,
            })
        }
    }

    const totalMappings = Object.values(campaignMappings).reduce(
        (sum, sourceMappings) => sum + Object.keys(sourceMappings).length,
        0
    )

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold mb-1">Campaign name mappings</h3>
                <p className="text-muted mb-4">
                    Map UTM campaign values to your ad platform campaign names for proper conversion attribution. Ad
                    platforms (LinkedIn, Google, TikTok, etc.) don't store UTM parameters—they only have campaign names.
                    PostHog joins conversions to paid campaigns by matching{' '}
                    <code className="text-xs">utm_campaign</code> values with campaign names from your ad integrations.
                    If your <code className="text-xs">utm_campaign</code> doesn't exactly match your ad platform
                    campaign name (e.g., "2025q3_paid_social_linkedin" vs "TOFU Video Views | LinkedIn | Global"), your
                    conversions won't attribute to the paid campaign. Use this to map multiple UTM variations to the
                    correct campaign name.
                </p>
            </div>

            {totalMappings > 0 && (
                <div className="border rounded p-4 space-y-4">
                    <h4 className="font-semibold">Current mappings ({totalMappings})</h4>
                    {Object.entries(campaignMappings).map(([source, sourceMappings]) => (
                        <div key={source} className="space-y-2">
                            <div className="font-medium text-sm text-muted">{source}</div>
                            {Object.entries(sourceMappings).map(([cleanName, rawValues]) => (
                                <div
                                    key={cleanName}
                                    className="flex items-start justify-between bg-bg-light rounded p-3"
                                >
                                    <div className="flex-1">
                                        <div className="font-medium mb-2">{cleanName}</div>
                                        <div className="flex flex-wrap gap-1">
                                            {(rawValues as string[]).map((rawValue) => (
                                                <LemonTag key={rawValue}>{rawValue}</LemonTag>
                                            ))}
                                        </div>
                                    </div>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconTrash />}
                                        onClick={() => removeMapping(source, cleanName)}
                                        tooltip="Remove mapping"
                                    />
                                </div>
                            ))}
                        </div>
                    ))}
                </div>
            )}

            <div className="border rounded p-4 space-y-3">
                <h4 className="font-semibold">Add new mapping</h4>

                <div className="space-y-3">
                    <div>
                        <label className="block text-sm font-medium mb-1">Data source</label>
                        <LemonSelect
                            value={selectedSource}
                            onChange={setSelectedSource}
                            options={[
                                { label: 'Select a source...', value: '' },
                                ...availableSources.map((source) => ({ label: source, value: source })),
                            ]}
                            fullWidth
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">Ad platform campaign name</label>
                        <LemonInput
                            value={newCleanName}
                            onChange={setNewCleanName}
                            placeholder="e.g., campaign name from the Data Warehouse table (e.g., TOFU Video Views | LinkedIn | Global)"
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            The exact campaign name from your ad platform (LinkedIn, Google, etc.)
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">UTM campaign values to map</label>
                        <LemonInput
                            value={newRawValues}
                            onChange={setNewRawValues}
                            placeholder="e.g., utm campaign from the url (e.g., 2025q3_paid_social_linkedin)"
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            Comma-separated list of utm_campaign values that should map to this campaign
                        </div>
                    </div>

                    <LemonButton
                        type="primary"
                        icon={<IconPlusSmall />}
                        onClick={addMapping}
                        disabled={!selectedSource || !newCleanName.trim() || !newRawValues.trim()}
                        fullWidth
                    >
                        Add mapping
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
