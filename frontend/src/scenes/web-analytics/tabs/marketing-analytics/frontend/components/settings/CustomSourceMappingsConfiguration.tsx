import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { MARKETING_DEFAULT_SOURCE_MAPPINGS, VALID_NATIVE_MARKETING_SOURCES } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

const SEPARATOR = ','

export interface CustomSourceMappingsConfigurationProps {
    sourceFilter?: string
    compact?: boolean
}

export function CustomSourceMappingsConfiguration({
    sourceFilter,
}: CustomSourceMappingsConfigurationProps): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCustomSourceMappings } = useActions(marketingAnalyticsSettingsLogic)

    const customMappings = marketingAnalyticsConfig?.custom_source_mappings || {}
    const [inputValues, setInputValues] = useState<Record<string, string>>({})

    const integrationsToShow = sourceFilter ? [sourceFilter] : [...VALID_NATIVE_MARKETING_SOURCES]

    const getInputValue = (integration: string): string => inputValues[integration] || ''
    const setInputValue = (integration: string, value: string): void => {
        setInputValues((prev) => ({ ...prev, [integration]: value }))
    }

    const updateMappings = (newMappings: Record<string, string[]>): void => {
        updateCustomSourceMappings(newMappings)
    }

    const getValidationError = (integration: string): string | null => {
        const inputValue = getInputValue(integration)
        if (!inputValue.trim()) {
            return null
        }

        const utmSourcesArray = inputValue
            .split(SEPARATOR)
            .map((v) => v.trim())
            .filter((v) => v.length > 0)

        const defaultSources =
            MARKETING_DEFAULT_SOURCE_MAPPINGS[integration as keyof typeof MARKETING_DEFAULT_SOURCE_MAPPINGS] || []
        const conflictsWithDefaults = utmSourcesArray.filter((source) =>
            defaultSources.some((def) => def.toLowerCase() === source.toLowerCase())
        )
        if (conflictsWithDefaults.length > 0) {
            return `${conflictsWithDefaults.join(', ')} already default`
        }

        const existingSources = customMappings[integration] || []
        const duplicates = utmSourcesArray.filter((source) =>
            (existingSources as string[]).some((existing) => existing.toLowerCase() === source.toLowerCase())
        )
        if (duplicates.length > 0) {
            return `${duplicates.join(', ')} already added`
        }

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
        const inputValue = getInputValue(integration)
        if (!integration || !inputValue.trim() || getValidationError(integration)) {
            return
        }

        const utmSourcesArray = inputValue
            .split(SEPARATOR)
            .map((v) => v.trim())
            .filter((v) => v.length > 0)

        const existingSources = customMappings[integration] || []

        updateMappings({
            ...customMappings,
            [integration]: [...existingSources, ...utmSourcesArray],
        })

        setInputValue(integration, '')
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
                    <p className="text-muted-foreground mb-4">
                        Add custom <code className="text-xs">utm_source</code> values to attribute conversions to your
                        ad platforms. Default sources are shown but cannot be removed.
                    </p>
                </div>
            )}

            <div className="border rounded overflow-hidden">
                <table className="w-full">
                    <thead>
                        <tr className="bg-card border-b">
                            {!sourceFilter && (
                                <th className="text-left text-xs font-semibold p-2 text-muted-foreground w-32">
                                    Integration
                                </th>
                            )}
                            <th className="text-left text-xs font-semibold p-2 text-muted-foreground">UTM sources</th>
                        </tr>
                    </thead>
                    <tbody>
                        {integrationsToShow.map((integration) => {
                            const defaults =
                                MARKETING_DEFAULT_SOURCE_MAPPINGS[
                                    integration as keyof typeof MARKETING_DEFAULT_SOURCE_MAPPINGS
                                ] || []
                            const custom = customMappings[integration] || []
                            const inputValue = getInputValue(integration)
                            const validationError = getValidationError(integration)
                            const isDisabled = !inputValue.trim() || !!validationError

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
                                                    className="border border-border-strong px-2 py-1"
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
                                                    value={inputValue}
                                                    onChange={(value) => setInputValue(integration, value)}
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
