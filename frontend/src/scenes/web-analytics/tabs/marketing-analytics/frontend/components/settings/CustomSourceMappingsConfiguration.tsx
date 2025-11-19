import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { externalDataSources } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { VALID_NATIVE_MARKETING_SOURCES } from '../../logic/utils'

const SEPARATOR = ','

// Default UTM source mappings for each integration (from backend adapters)
const DEFAULT_SOURCE_MAPPINGS: Record<string, string[]> = {
    GoogleAds: [
        'google',
        'adwords',
        'youtube',
        'display',
        'gmail',
        'google_maps',
        'google_play',
        'google_discover',
        'admob',
        'waze',
    ],
    LinkedinAds: ['linkedin', 'li'],
    MetaAds: [
        'meta',
        'facebook',
        'instagram',
        'messenger',
        'fb',
        'whatsapp',
        'audience_network',
        'facebook_marketplace',
        'threads',
    ],
    TikTokAds: ['tiktok'],
    RedditAds: ['reddit'],
}

export interface CustomSourceMappingsConfigurationProps {
    sourceFilter?: string
}

export function CustomSourceMappingsConfiguration({
    sourceFilter,
}: CustomSourceMappingsConfigurationProps): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCustomSourceMappings } = useActions(marketingAnalyticsSettingsLogic)

    const customMappings = marketingAnalyticsConfig?.custom_source_mappings || {}
    const [newUtmSources, setNewUtmSources] = useState('')

    const availableIntegrations = externalDataSources.filter((source) =>
        VALID_NATIVE_MARKETING_SOURCES.includes(source as any)
    )

    // Get integrations to display
    const integrationsToShow = sourceFilter ? [sourceFilter] : availableIntegrations

    const updateMappings = (newMappings: Record<string, string[]>): void => {
        updateCustomSourceMappings(newMappings)
    }

    const getValidationError = (integration: string): string | null => {
        if (!newUtmSources.trim()) {
            return null
        }

        const utmSourcesArray = newUtmSources
            .split(SEPARATOR)
            .map((v) => v.trim())
            .filter((v) => v.length > 0)

        // Check for conflicts with defaults
        const defaultSources = DEFAULT_SOURCE_MAPPINGS[integration] || []
        const conflictsWithDefaults = utmSourcesArray.filter((source) =>
            defaultSources.some((def) => def.toLowerCase() === source.toLowerCase())
        )
        if (conflictsWithDefaults.length > 0) {
            return `${conflictsWithDefaults.join(', ')} already default`
        }

        // Check for duplicates within the same integration
        const existingSources = customMappings[integration] || []
        const duplicates = utmSourcesArray.filter((source) =>
            (existingSources as string[]).some((existing) => existing.toLowerCase() === source.toLowerCase())
        )
        if (duplicates.length > 0) {
            return `${duplicates.join(', ')} already added`
        }

        // Check for conflicts with other integrations
        for (const [otherIntegration, sources] of Object.entries(customMappings)) {
            if (otherIntegration === integration) {
                continue
            }
            for (const newSource of utmSourcesArray) {
                for (const existingSource of sources as string[]) {
                    if (newSource.toLowerCase() === existingSource.toLowerCase()) {
                        return `"${newSource}" used in ${otherIntegration}`
                    }
                }
            }
        }

        return null
    }

    const addMapping = (integration: string): void => {
        if (!integration || !newUtmSources.trim() || getValidationError(integration)) {
            return
        }

        const utmSourcesArray = newUtmSources
            .split(SEPARATOR)
            .map((v) => v.trim())
            .filter((v) => v.length > 0)

        const existingSources = customMappings[integration] || []

        updateMappings({
            ...customMappings,
            [integration]: [...existingSources, ...utmSourcesArray],
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

    return (
        <div className="space-y-4">
            {!sourceFilter && (
                <div>
                    <h3 className="text-lg font-semibold mb-1">Custom UTM source mappings</h3>
                    <p className="text-muted mb-4">
                        Add custom <code className="text-xs">utm_source</code> values to attribute conversions to your
                        ad platforms. Default sources are shown but cannot be removed.
                    </p>
                </div>
            )}

            <div className="border rounded overflow-hidden">
                <table className="w-full">
                    <thead>
                        <tr className="bg-bg-light border-b">
                            {!sourceFilter && (
                                <th className="text-left text-xs font-semibold p-2 text-muted w-32">Integration</th>
                            )}
                            <th className="text-left text-xs font-semibold p-2 text-muted">UTM sources</th>
                        </tr>
                    </thead>
                    <tbody>
                        {integrationsToShow.map((integration) => {
                            const defaults = DEFAULT_SOURCE_MAPPINGS[integration] || []
                            const custom = customMappings[integration] || []

                            const validationError = getValidationError(integration)
                            const isDisabled = !newUtmSources.trim() || !!validationError

                            return (
                                <tr key={integration} className="border-b last:border-b-0">
                                    {!sourceFilter && (
                                        <td className="p-2 text-sm align-top font-medium">{integration}</td>
                                    )}
                                    <td className="p-2 align-top">
                                        <div className="flex flex-wrap gap-1 items-center">
                                            {defaults.map((source) => (
                                                <LemonTag
                                                    key={source}
                                                    size="small"
                                                    type="muted"
                                                    className="border border-border-bold px-2 py-1"
                                                >
                                                    {source}
                                                </LemonTag>
                                            ))}
                                            {(custom as string[]).map((source) => (
                                                <LemonTag
                                                    key={source}
                                                    size="small"
                                                    type="primary"
                                                    closable
                                                    onClose={() => removeMapping(integration, source)}
                                                >
                                                    {source}
                                                </LemonTag>
                                            ))}
                                            <div className="flex gap-1 items-center">
                                                <LemonInput
                                                    value={newUtmSources}
                                                    onChange={setNewUtmSources}
                                                    placeholder="Add custom sources"
                                                    size="small"
                                                    className="w-40"
                                                />
                                                <LemonButton
                                                    type="primary"
                                                    size="small"
                                                    icon={<IconPlusSmall />}
                                                    onClick={() => addMapping(integration)}
                                                    disabled={isDisabled}
                                                    disabledReason={validationError || undefined}
                                                    tooltip={!validationError ? 'Add custom sources' : undefined}
                                                />
                                            </div>
                                        </div>
                                    </td>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
