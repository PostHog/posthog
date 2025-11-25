import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { externalDataSources } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { VALID_NATIVE_MARKETING_SOURCES } from '../../logic/utils'

const SEPARATOR = ','

export function CustomSourceMappingsConfiguration(): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCustomSourceMappings } = useActions(marketingAnalyticsSettingsLogic)

    const customMappings = marketingAnalyticsConfig?.custom_source_mappings || {}
    const [selectedIntegration, setSelectedIntegration] = useState<string>('')
    const [newUtmSources, setNewUtmSources] = useState('')

    const availableIntegrations = externalDataSources.filter((source) =>
        VALID_NATIVE_MARKETING_SOURCES.includes(source as any)
    )

    const updateMappings = (newMappings: Record<string, string[]>): void => {
        updateCustomSourceMappings(newMappings)
    }

    const addMapping = (): void => {
        if (!selectedIntegration || !newUtmSources.trim()) {
            return
        }

        const utmSourcesArray = newUtmSources
            .split(SEPARATOR)
            .map((v) => v.trim())
            .filter((v) => v.length > 0)

        // Check for conflicts: same source cannot be in multiple integrations
        const conflicts: string[] = []
        for (const [integration, sources] of Object.entries(customMappings)) {
            if (integration === selectedIntegration) {
                continue // Skip the current integration
            }
            for (const newSource of utmSourcesArray) {
                for (const existingSource of sources as string[]) {
                    if (newSource.toLowerCase() === existingSource.toLowerCase()) {
                        conflicts.push(`"${newSource}" is already used in ${integration}`)
                    }
                }
            }
        }

        if (conflicts.length > 0) {
            alert(
                `Cannot add custom sources:\n\n${conflicts.join('\n')}\n\nEach custom UTM source must be unique across all integrations. Please use different source names or remove the existing mapping first.`
            )
            return
        }

        const existingSources = customMappings[selectedIntegration] || []

        updateMappings({
            ...customMappings,
            [selectedIntegration]: [...existingSources, ...utmSourcesArray],
        })

        setNewUtmSources('')
    }

    const removeMapping = (integration: string, utmSource: string): void => {
        const integrationSources = [...(customMappings[integration] || [])]
        const updatedSources = integrationSources.filter((source) => source !== utmSource)

        if (updatedSources.length === 0) {
            const newMappings = { ...customMappings }
            delete newMappings[integration]
            updateMappings(newMappings)
        } else {
            updateMappings({
                ...customMappings,
                [integration]: updatedSources,
            })
        }
    }

    const totalMappings = Object.values(customMappings).reduce((sum, sources) => sum + sources.length, 0)

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold mb-1">Custom UTM source mappings</h3>
                <p className="text-muted mb-4">
                    Add custom <code className="text-xs">utm_source</code> values that should be attributed to your
                    integrated ad platforms. For example, if you tag links with{' '}
                    <code className="text-xs">utm_source=partner_a</code> but want conversions attributed to your Google
                    Ads campaigns, add "partner_a" as a custom source for GoogleAds. This supplements the default source
                    mappings (e.g., GoogleAds automatically includes "google", "youtube", "adwords", etc.).
                </p>
                <p className="text-muted-alt text-xs mb-4">
                    <strong>Important:</strong> Each custom UTM source value must be unique across all integrations. You
                    cannot map the same source value (e.g., "partner_a") to multiple platforms.
                </p>
            </div>

            {totalMappings > 0 && (
                <div className="border rounded p-4 space-y-4">
                    <h4 className="font-semibold">Current custom sources ({totalMappings})</h4>
                    {Object.entries(customMappings).map(([integration, utmSources]) => (
                        <div key={integration} className="space-y-2">
                            <div className="font-medium text-sm text-muted">{integration}</div>
                            <div className="flex flex-wrap gap-2">
                                {(utmSources as string[]).map((utmSource) => (
                                    <div
                                        key={utmSource}
                                        className="flex items-center gap-2 bg-bg-light rounded px-3 py-2"
                                    >
                                        <LemonTag>{utmSource}</LemonTag>
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            icon={<IconTrash />}
                                            onClick={() => removeMapping(integration, utmSource)}
                                            tooltip="Remove custom source"
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <div className="border rounded p-4 space-y-3">
                <h4 className="font-semibold">Add custom source</h4>

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
                                })),
                            ]}
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            The ad platform integration to attribute these UTM sources to
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">Custom UTM source values</label>
                        <LemonInput
                            value={newUtmSources}
                            onChange={setNewUtmSources}
                            placeholder="e.g., partner_a, influencer_campaign, custom_source"
                            fullWidth
                        />
                        <div className="text-xs text-muted mt-1">
                            Comma-separated list of <code className="text-xs">utm_source</code> values that should map
                            to this integration
                        </div>
                    </div>

                    <LemonButton
                        type="primary"
                        icon={<IconPlusSmall />}
                        onClick={addMapping}
                        disabled={!selectedIntegration || !newUtmSources.trim()}
                        fullWidth
                    >
                        Add custom sources
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
