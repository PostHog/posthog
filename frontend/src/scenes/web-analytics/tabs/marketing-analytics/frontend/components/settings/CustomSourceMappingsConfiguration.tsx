import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { MARKETING_DEFAULT_SOURCE_MAPPINGS } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { getEnabledNativeMarketingSources } from '../../logic/utils'
import { parseCommaSeparatedValues, removeSourceFromMappings } from '../NonIntegratedConversionsTable/mappingUtils'

export interface CustomSourceMappingsConfigurationProps {
    sourceFilter?: string
    initialUtmValue?: string
}

export function CustomSourceMappingsConfiguration({
    sourceFilter,
    initialUtmValue,
}: CustomSourceMappingsConfigurationProps): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCustomSourceMappings } = useActions(marketingAnalyticsSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const customMappings = marketingAnalyticsConfig?.custom_source_mappings || {}
    const [inputValues, setInputValues] = useState<Record<string, string>>(() =>
        sourceFilter && initialUtmValue ? { [sourceFilter]: initialUtmValue } : {}
    )

    const enabledSources = getEnabledNativeMarketingSources(featureFlags)
    const integrationsToShow = sourceFilter ? [sourceFilter] : [...enabledSources]

    const getInputValue = (integration: string): string => inputValues[integration] || ''
    const setInputValue = (integration: string, value: string): void => {
        setInputValues((prev) => ({ ...prev, [integration]: value }))
    }

    const getValidationError = (integration: string): string | null => {
        const inputValue = getInputValue(integration)
        if (!inputValue.trim()) {
            return null
        }

        const utmSources = parseCommaSeparatedValues(inputValue)
        const defaults =
            MARKETING_DEFAULT_SOURCE_MAPPINGS[integration as keyof typeof MARKETING_DEFAULT_SOURCE_MAPPINGS] || []

        const conflictsWithDefaults = utmSources.filter((s) =>
            defaults.some((d) => d.toLowerCase() === s.toLowerCase())
        )
        if (conflictsWithDefaults.length > 0) {
            return `${conflictsWithDefaults.join(', ')} already default`
        }

        const existingSources = customMappings[integration] || []
        const duplicates = utmSources.filter((s) =>
            (existingSources as string[]).some((e) => e.toLowerCase() === s.toLowerCase())
        )
        if (duplicates.length > 0) {
            return `${duplicates.join(', ')} already added`
        }

        for (const [otherIntegration, sources] of Object.entries(customMappings)) {
            if (otherIntegration === integration) {
                continue
            }
            const conflicts = utmSources.filter((s) =>
                (sources as string[]).some((e) => e.toLowerCase() === s.toLowerCase())
            )
            if (conflicts.length > 0) {
                return `"${conflicts[0]}" used in ${otherIntegration}`
            }
        }

        return null
    }

    const addMapping = (integration: string): void => {
        const inputValue = getInputValue(integration)
        if (!integration || !inputValue.trim() || getValidationError(integration)) {
            return
        }

        const utmSources = parseCommaSeparatedValues(inputValue)
        const existingSources = customMappings[integration] || []

        updateCustomSourceMappings({
            ...customMappings,
            [integration]: [...existingSources, ...utmSources],
        })
        setInputValue(integration, '')
    }

    const removeMapping = (integration: string, utmSource: string): void => {
        updateCustomSourceMappings(removeSourceFromMappings(marketingAnalyticsConfig, integration as any, utmSource))
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
                            const defaults =
                                MARKETING_DEFAULT_SOURCE_MAPPINGS[
                                    integration as keyof typeof MARKETING_DEFAULT_SOURCE_MAPPINGS
                                ] || []
                            const custom = customMappings[integration] || []
                            const inputValue = getInputValue(integration)
                            const validationError = getValidationError(integration)

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
