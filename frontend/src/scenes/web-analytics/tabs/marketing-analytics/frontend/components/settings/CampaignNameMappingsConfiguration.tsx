import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconPlusSmall, IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, LemonInputSelect, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { MatchField, VALID_NATIVE_MARKETING_SOURCES, externalDataSources } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { getGlobalCampaignMapping } from '../NonIntegratedConversionsTable/mappingUtils'

const SEPARATOR = ','

export interface CampaignNameMappingsConfigurationProps {
    sourceFilter?: string
    compact?: boolean
    /** Initial UTM value to pre-populate in the input */
    initialUtmValue?: string
}

export function CampaignNameMappingsConfiguration({
    sourceFilter,
    compact = false,
    initialUtmValue,
}: CampaignNameMappingsConfigurationProps): JSX.Element {
    const { marketingAnalyticsConfig, integrationCampaigns, integrationCampaignsLoading } = useValues(
        marketingAnalyticsSettingsLogic
    )
    const { updateCampaignNameMappings, loadIntegrationCampaigns } = useActions(marketingAnalyticsSettingsLogic)

    const campaignMappings = marketingAnalyticsConfig?.campaign_name_mappings || {}
    const fieldPreferences = marketingAnalyticsConfig?.campaign_field_preferences || {}
    const [selectedSource, setSelectedSource] = useState<string>(sourceFilter || '')
    const [newCleanName, setNewCleanName] = useState('')
    const [newRawValues, setNewRawValues] = useState(initialUtmValue || '')

    // Update newRawValues when initialUtmValue changes
    useEffect(() => {
        if (initialUtmValue) {
            setNewRawValues(initialUtmValue)
        }
    }, [initialUtmValue])

    const availableSources = externalDataSources.filter((source) =>
        VALID_NATIVE_MARKETING_SOURCES.includes(source as any)
    )

    // Load campaigns for the selected integration (only once on mount or when integration changes)
    const currentIntegration = sourceFilter || selectedSource

    useEffect(() => {
        if (currentIntegration) {
            // Only load if not already loaded or loading
            const hasLoaded = !!integrationCampaigns[currentIntegration]
            const isLoading = !!integrationCampaignsLoading[currentIntegration]
            if (!hasLoaded && !isLoading) {
                loadIntegrationCampaigns(currentIntegration)
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentIntegration])

    // Filter mappings by source if sourceFilter is provided
    const filteredMappings = sourceFilter ? { [sourceFilter]: campaignMappings[sourceFilter] || {} } : campaignMappings

    // Get the match field preference for column header
    const matchField = sourceFilter
        ? fieldPreferences[sourceFilter]?.match_field || MatchField.CAMPAIGN_NAME
        : MatchField.CAMPAIGN_NAME
    const columnHeader = matchField === MatchField.CAMPAIGN_ID ? 'Campaign ID' : 'Campaign name'

    // Get campaign options for autocomplete
    const campaigns = integrationCampaigns[currentIntegration] || []
    const campaignOptions = campaigns.map((c: { name: string; id: string }) => ({
        key: matchField === MatchField.CAMPAIGN_ID ? c.id : c.name,
        label: matchField === MatchField.CAMPAIGN_ID ? `${c.id} (${c.name})` : c.name,
    }))

    // Check if any of the input utm_campaign values are already mapped globally
    const alreadyMappedValues = useMemo(() => {
        if (!newRawValues.trim()) {
            return []
        }

        const rawValuesArray = newRawValues
            .split(SEPARATOR)
            .map((v) => v.trim())
            .filter((v) => v.length > 0)

        const mapped: Array<{ value: string; integration: string; campaignName: string }> = []
        for (const value of rawValuesArray) {
            const existing = getGlobalCampaignMapping(value, marketingAnalyticsConfig)
            if (existing) {
                mapped.push({
                    value,
                    integration: existing.integration,
                    campaignName: existing.campaignName,
                })
            }
        }
        return mapped
    }, [newRawValues, marketingAnalyticsConfig])

    const hasAlreadyMappedValues = alreadyMappedValues.length > 0

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

        // Filter out any values that are already mapped globally
        const filteredValues = rawValuesArray.filter((value) => {
            const existing = getGlobalCampaignMapping(value, marketingAnalyticsConfig)
            return existing === null
        })

        if (filteredValues.length === 0) {
            // All values were already mapped
            return
        }

        const sourceMappings = campaignMappings[selectedSource] || {}
        const existingValues = sourceMappings[newCleanName.trim()] || []

        // Merge with existing values, keeping only unique ones
        const mergedValues = [...new Set([...existingValues, ...filteredValues])]

        updateMappings({
            ...campaignMappings,
            [selectedSource]: {
                ...sourceMappings,
                [newCleanName.trim()]: mergedValues,
            },
        })

        setNewCleanName('')
        setNewRawValues('')
    }

    const removeUtmValue = (source: string, cleanName: string, utmValue: string): void => {
        const sourceMappings = { ...campaignMappings[source] }
        const currentValues = [...(sourceMappings[cleanName] || [])]
        const updatedValues = currentValues.filter((v) => v !== utmValue)

        if (updatedValues.length === 0) {
            // Remove the entire mapping if no utm values left
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
        } else {
            updateMappings({
                ...campaignMappings,
                [source]: {
                    ...sourceMappings,
                    [cleanName]: updatedValues,
                },
            })
        }
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

    return (
        <div className="space-y-4">
            {!compact && (
                <div>
                    <h3 className="text-lg font-semibold mb-1">Campaign name mappings</h3>
                    <p className="text-muted mb-4">
                        Map UTM campaign values to your ad platform campaign names for proper conversion attribution. Ad
                        platforms (LinkedIn, Google, TikTok, etc.) don't store UTM parameters—they only have campaign
                        names. PostHog joins conversions to paid campaigns by matching{' '}
                        <code className="text-xs">utm_campaign</code> values with campaign names from your ad
                        integrations. If your <code className="text-xs">utm_campaign</code> doesn't exactly match your
                        ad platform campaign name (e.g., "2025q3_paid_social_linkedin" vs "TOFU Video Views | LinkedIn |
                        Global"), your conversions won't attribute to the paid campaign. Use this to map multiple UTM
                        variations to the correct campaign name.
                    </p>
                </div>
            )}
            {compact && <h4 className="font-semibold text-sm mb-2">Campaign name mappings</h4>}

            <div className="border rounded overflow-x-auto">
                <table className="w-full table-fixed">
                    <thead>
                        <tr className="bg-bg-light border-b">
                            {!sourceFilter && (
                                <th className="text-left text-xs font-semibold p-2 text-muted w-1/4">Source</th>
                            )}
                            <th className="text-left text-xs font-semibold p-2 text-muted w-1/3">{columnHeader}</th>
                            <th className="text-left text-xs font-semibold p-2 text-muted">utm_campaign</th>
                            <th className="text-right text-xs font-semibold p-2 text-muted w-16">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {Object.entries(filteredMappings).map(([source, sourceMappings]) => {
                            if (!sourceMappings || Object.keys(sourceMappings).length === 0) {
                                return null
                            }
                            return Object.entries(sourceMappings).map(([cleanName, rawValues]) => (
                                <tr key={`${source}-${cleanName}`} className="border-b last:border-b-0">
                                    {!sourceFilter && <td className="p-2 text-sm align-top">{source}</td>}
                                    <td className="p-2 text-sm align-top font-medium">{cleanName}</td>
                                    <td className="p-2 align-top">
                                        <div className="flex flex-wrap gap-1">
                                            {(rawValues as string[]).map((rawValue) => (
                                                <LemonTag
                                                    key={rawValue}
                                                    size="small"
                                                    closable
                                                    onClose={() => removeUtmValue(source, cleanName, rawValue)}
                                                >
                                                    {rawValue}
                                                </LemonTag>
                                            ))}
                                        </div>
                                    </td>
                                    <td className="p-2 text-right align-top">
                                        <LemonButton
                                            type="tertiary"
                                            status="danger"
                                            size="small"
                                            icon={<IconTrash />}
                                            onClick={() => removeMapping(source, cleanName)}
                                            tooltip="Remove mapping"
                                        />
                                    </td>
                                </tr>
                            ))
                        })}
                        {/* Add new mapping row */}
                        <tr className="bg-bg-light">
                            {!sourceFilter && (
                                <td className="p-2 align-top">
                                    <LemonSelect
                                        value={selectedSource}
                                        onChange={setSelectedSource}
                                        options={[
                                            { label: 'Source...', value: '' },
                                            ...availableSources.map((source) => ({ label: source, value: source })),
                                        ]}
                                        size="small"
                                        fullWidth
                                    />
                                </td>
                            )}
                            <td className="p-2 align-top">
                                <LemonInputSelect
                                    value={newCleanName ? [newCleanName] : []}
                                    onChange={(values) => setNewCleanName(values[0] || '')}
                                    options={campaignOptions}
                                    placeholder={
                                        integrationCampaignsLoading[currentIntegration]
                                            ? 'Loading campaigns...'
                                            : matchField === MatchField.CAMPAIGN_ID
                                              ? 'Campaign ID'
                                              : 'Campaign name'
                                    }
                                    mode="single"
                                    allowCustomValues
                                    size="small"
                                    loading={integrationCampaignsLoading[currentIntegration]}
                                />
                            </td>
                            <td className="p-2 align-top">
                                <div className="flex flex-col gap-1">
                                    <LemonInput
                                        value={newRawValues}
                                        onChange={setNewRawValues}
                                        placeholder="utm_campaign values (comma-separated)"
                                        size="small"
                                        fullWidth
                                    />
                                    {hasAlreadyMappedValues && (
                                        <div className="flex items-start gap-1 text-warning text-xs">
                                            <IconWarning className="w-3 h-3 mt-0.5 flex-shrink-0" />
                                            <span>
                                                {alreadyMappedValues.length === 1
                                                    ? `"${alreadyMappedValues[0].value}" is already mapped to ${alreadyMappedValues[0].integration}: ${alreadyMappedValues[0].campaignName}`
                                                    : `${alreadyMappedValues.length} values are already mapped elsewhere`}
                                            </span>
                                        </div>
                                    )}
                                </div>
                            </td>
                            <td className="p-2 text-right align-top">
                                <Tooltip
                                    title={
                                        hasAlreadyMappedValues
                                            ? 'Some utm_campaign values are already mapped. Each value can only be in one mapping.'
                                            : 'Add mapping'
                                    }
                                >
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        icon={<IconPlusSmall />}
                                        onClick={addMapping}
                                        disabled={
                                            (!sourceFilter && !selectedSource) ||
                                            !newCleanName.trim() ||
                                            !newRawValues.trim() ||
                                            hasAlreadyMappedValues
                                        }
                                    />
                                </Tooltip>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    )
}
