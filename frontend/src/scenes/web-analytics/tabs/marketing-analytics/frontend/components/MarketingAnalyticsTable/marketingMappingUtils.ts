import {
    MARKETING_DEFAULT_SOURCE_MAPPINGS,
    MarketingAnalyticsConfig,
    NativeMarketingSource,
    VALID_NATIVE_MARKETING_SOURCES,
} from '~/queries/schema/schema-general'

/**
 * Check if a UTM source value is mapped to any integration
 * Returns the integration name if mapped, null otherwise
 */
export function getIntegrationForSource(
    utmSource: string,
    config: MarketingAnalyticsConfig | null
): NativeMarketingSource | null {
    if (!utmSource) {
        return null
    }

    const normalizedSource = utmSource.toLowerCase().trim()

    // Check default mappings first
    for (const integration of VALID_NATIVE_MARKETING_SOURCES) {
        const defaults = MARKETING_DEFAULT_SOURCE_MAPPINGS[integration] || []
        if (defaults.some((d) => d.toLowerCase() === normalizedSource)) {
            return integration
        }
    }

    // Check custom mappings
    const customMappings = config?.custom_source_mappings || {}
    for (const [integration, sources] of Object.entries(customMappings)) {
        if ((sources as string[]).some((s) => s.toLowerCase() === normalizedSource)) {
            return integration as NativeMarketingSource
        }
    }

    return null
}

/**
 * Check if a UTM source is unmapped (not in any integration's default or custom mappings)
 */
export function isSourceUnmapped(utmSource: string, config: MarketingAnalyticsConfig | null): boolean {
    return getIntegrationForSource(utmSource, config) === null
}

/**
 * Get integrations that a source could be mapped to
 * Excludes integrations where this source conflicts with existing mappings
 */
export function getAvailableIntegrationsForSource(
    utmSource: string,
    config: MarketingAnalyticsConfig | null
): NativeMarketingSource[] {
    if (!utmSource) {
        return []
    }

    const normalizedSource = utmSource.toLowerCase().trim()
    const available: NativeMarketingSource[] = []

    for (const integration of VALID_NATIVE_MARKETING_SOURCES) {
        // Check if it conflicts with defaults
        const defaults = MARKETING_DEFAULT_SOURCE_MAPPINGS[integration] || []
        if (defaults.some((d) => d.toLowerCase() === normalizedSource)) {
            continue
        }

        // Check if already in custom mappings for another integration
        const customMappings = config?.custom_source_mappings || {}
        let conflictsWithOther = false
        for (const [otherIntegration, sources] of Object.entries(customMappings)) {
            if (otherIntegration !== integration) {
                if ((sources as string[]).some((s) => s.toLowerCase() === normalizedSource)) {
                    conflictsWithOther = true
                    break
                }
            }
        }

        if (!conflictsWithOther) {
            available.push(integration)
        }
    }

    return available
}

/**
 * Check if a UTM campaign value is mapped for a specific integration
 */
export function isCampaignMappedForIntegration(
    utmCampaign: string,
    integration: string,
    config: MarketingAnalyticsConfig | null
): boolean {
    if (!utmCampaign || !integration) {
        return false
    }

    const campaignMappings = config?.campaign_name_mappings || {}
    const integrationMappings = campaignMappings[integration] || {}

    // Check if this UTM campaign is in any mapping's values
    for (const rawValues of Object.values(integrationMappings)) {
        if ((rawValues as string[]).some((v) => v.toLowerCase() === utmCampaign.toLowerCase())) {
            return true
        }
    }

    return false
}

/**
 * Check if a UTM campaign value is unmapped for all integrations
 */
export function isCampaignUnmapped(utmCampaign: string, config: MarketingAnalyticsConfig | null): boolean {
    if (!utmCampaign) {
        return false
    }

    for (const integration of VALID_NATIVE_MARKETING_SOURCES) {
        if (isCampaignMappedForIntegration(utmCampaign, integration, config)) {
            return false
        }
    }

    return true
}

/**
 * Check if a UTM campaign value is already mapped to ANY integration globally.
 * Returns the integration and campaign name if mapped, null otherwise.
 * This enforces the constraint that a utm_campaign can only be in one mapping.
 */
export function getGlobalCampaignMapping(
    utmCampaign: string,
    config: MarketingAnalyticsConfig | null
): { integration: NativeMarketingSource; campaignName: string } | null {
    if (!utmCampaign) {
        return null
    }

    const normalizedCampaign = utmCampaign.toLowerCase().trim()
    const campaignMappings = config?.campaign_name_mappings || {}

    for (const [integration, integrationMappings] of Object.entries(campaignMappings)) {
        for (const [campaignName, rawValues] of Object.entries(integrationMappings as Record<string, string[]>)) {
            if (rawValues.some((v) => v.toLowerCase().trim() === normalizedCampaign)) {
                return {
                    integration: integration as NativeMarketingSource,
                    campaignName,
                }
            }
        }
    }

    return null
}

/**
 * Check if a utm_campaign value is already mapped (returns true if mapped to any integration)
 */
export function isCampaignMappedGlobally(utmCampaign: string, config: MarketingAnalyticsConfig | null): boolean {
    return getGlobalCampaignMapping(utmCampaign, config) !== null
}

/**
 * Get integrations where a campaign could be mapped.
 * IMPORTANT: A utm_campaign can only be mapped to ONE integration globally.
 * Returns empty array if already mapped to any integration.
 */
export function getAvailableIntegrationsForCampaign(
    utmCampaign: string,
    config: MarketingAnalyticsConfig | null
): NativeMarketingSource[] {
    if (!utmCampaign) {
        return []
    }

    // If already mapped to any integration, no integrations are available
    if (isCampaignMappedGlobally(utmCampaign, config)) {
        return []
    }

    // Return all integrations since this campaign isn't mapped anywhere yet
    return [...VALID_NATIVE_MARKETING_SOURCES]
}

export type SourceMappingStatus =
    | { type: 'unmapped' }
    | { type: 'default'; integration: NativeMarketingSource }
    | { type: 'custom'; integration: NativeMarketingSource }

/**
 * Get detailed mapping status for a UTM source
 */
export function getSourceMappingStatus(
    utmSource: string,
    config: MarketingAnalyticsConfig | null
): SourceMappingStatus {
    if (!utmSource) {
        return { type: 'unmapped' }
    }

    const normalizedSource = utmSource.toLowerCase().trim()

    // Check default mappings first
    for (const integration of VALID_NATIVE_MARKETING_SOURCES) {
        const defaults = MARKETING_DEFAULT_SOURCE_MAPPINGS[integration] || []
        if (defaults.some((d) => d.toLowerCase() === normalizedSource)) {
            return { type: 'default', integration }
        }
    }

    // Check custom mappings
    const customMappings = config?.custom_source_mappings || {}
    for (const [integration, sources] of Object.entries(customMappings)) {
        if ((sources as string[]).some((s) => s.toLowerCase() === normalizedSource)) {
            return { type: 'custom', integration: integration as NativeMarketingSource }
        }
    }

    return { type: 'unmapped' }
}

export type CampaignMappingInfo = {
    integration: NativeMarketingSource
    campaignName: string
}

/**
 * Get all integrations where a UTM campaign is mapped (via manual mappings)
 */
export function getCampaignMappings(
    utmCampaign: string,
    config: MarketingAnalyticsConfig | null
): CampaignMappingInfo[] {
    if (!utmCampaign) {
        return []
    }

    const mappings: CampaignMappingInfo[] = []
    const campaignMappings = config?.campaign_name_mappings || {}

    for (const [integration, integrationMappings] of Object.entries(campaignMappings)) {
        for (const [campaignName, rawValues] of Object.entries(integrationMappings as Record<string, string[]>)) {
            if (rawValues.some((v) => v.toLowerCase() === utmCampaign.toLowerCase())) {
                mappings.push({
                    integration: integration as NativeMarketingSource,
                    campaignName,
                })
            }
        }
    }

    return mappings
}

export type AutoMatchedCampaignInfo = {
    integration: NativeMarketingSource
    matchedBy: 'name' | 'id'
    campaignName: string
    campaignId: string
}

/**
 * Check if a UTM campaign is auto-matched to any integration's campaign data
 * This happens when the UTM campaign value exactly matches a campaign name or ID
 */
export function getAutoMatchedCampaigns(
    utmCampaign: string,
    integrationCampaigns: Record<string, Array<{ name: string; id: string }>>,
    config: MarketingAnalyticsConfig | null
): AutoMatchedCampaignInfo[] {
    if (!utmCampaign) {
        return []
    }

    const normalizedCampaign = utmCampaign.toLowerCase().trim()
    const matches: AutoMatchedCampaignInfo[] = []
    const fieldPreferences = config?.campaign_field_preferences || {}

    for (const [integration, campaigns] of Object.entries(integrationCampaigns)) {
        const matchField = fieldPreferences[integration]?.match_field || 'campaign_name'

        for (const campaign of campaigns) {
            // Check based on the configured match field preference
            if (matchField === 'campaign_id') {
                if (campaign.id.toLowerCase() === normalizedCampaign) {
                    matches.push({
                        integration: integration as NativeMarketingSource,
                        matchedBy: 'id',
                        campaignName: campaign.name,
                        campaignId: campaign.id,
                    })
                    break
                }
            } else {
                if (campaign.name.toLowerCase() === normalizedCampaign) {
                    matches.push({
                        integration: integration as NativeMarketingSource,
                        matchedBy: 'name',
                        campaignName: campaign.name,
                        campaignId: campaign.id,
                    })
                    break
                }
            }
        }
    }

    return matches
}

/**
 * Check if a campaign has any actions available (not fully auto-matched to all available integrations)
 */
export function campaignHasAvailableActions(
    utmCampaign: string,
    integrationCampaigns: Record<string, Array<{ name: string; id: string }>>,
    integrationCampaignTables: Record<string, string>,
    config: MarketingAnalyticsConfig | null
): boolean {
    if (!utmCampaign) {
        return false
    }

    // Get auto-matched integrations
    const autoMatched = getAutoMatchedCampaigns(utmCampaign, integrationCampaigns, config)
    const autoMatchedIntegrations = new Set(autoMatched.map((m) => m.integration))

    // Get manually mapped integrations
    const manualMappings = getCampaignMappings(utmCampaign, config)
    const manuallyMappedIntegrations = new Set(manualMappings.map((m) => m.integration))

    // Get available integrations (those with data)
    const availableIntegrations = VALID_NATIVE_MARKETING_SOURCES.filter(
        (integration) => !!integrationCampaignTables[integration]
    )

    // Check if there are any integrations where we can still map
    const hasMapAction = availableIntegrations.some(
        (integration) => !autoMatchedIntegrations.has(integration) && !manuallyMappedIntegrations.has(integration)
    )

    // Check if there are manual mappings to remove
    const hasRemoveAction = manualMappings.length > 0

    return hasMapAction || hasRemoveAction
}
