import {
    MARKETING_DEFAULT_SOURCE_MAPPINGS,
    MarketingAnalyticsConfig,
    MarketingAnalyticsItem,
    NativeMarketingSource,
    VALID_NATIVE_MARKETING_SOURCES,
} from '~/queries/schema/schema-general'

/** Parse comma-separated values into a trimmed array */
export const parseCommaSeparatedValues = (value: string): string[] =>
    value
        .split(',')
        .map((v) => v.trim())
        .filter((v) => v.length > 0)

/** Extract string value from a MarketingAnalyticsItem or raw value */
export function extractStringValue(value: unknown): string {
    if (value == null) {
        return ''
    }
    if (typeof value === 'object' && 'value' in value) {
        const item = value as MarketingAnalyticsItem
        return String(item.value ?? '').trim()
    }
    return String(value).trim()
}

/** Create updated source mappings with a source removed from an integration */
export function removeSourceFromMappings(
    config: MarketingAnalyticsConfig | null,
    integration: NativeMarketingSource,
    sourceToRemove: string
): Record<string, string[]> {
    const customMappings = { ...config?.custom_source_mappings }
    const integrationSources = [...(customMappings[integration] || [])]
    const updatedSources = integrationSources.filter((s) => s.toLowerCase() !== sourceToRemove.toLowerCase())

    if (updatedSources.length === 0) {
        delete customMappings[integration]
    } else {
        customMappings[integration] = updatedSources
    }

    return customMappings
}

/** Create updated campaign mappings with a campaign removed from an integration */
export function removeCampaignFromMappings(
    config: MarketingAnalyticsConfig | null,
    integration: NativeMarketingSource,
    campaignName: string,
    campaignToRemove: string
): Record<string, Record<string, string[]>> {
    const campaignMappings = { ...config?.campaign_name_mappings }
    const integrationMappings = { ...campaignMappings[integration] }
    const currentValues = [...(integrationMappings[campaignName] || [])]
    const updatedValues = currentValues.filter((v) => v.toLowerCase() !== campaignToRemove.toLowerCase())

    if (updatedValues.length === 0) {
        delete integrationMappings[campaignName]
        if (Object.keys(integrationMappings).length === 0) {
            delete campaignMappings[integration]
        } else {
            campaignMappings[integration] = integrationMappings
        }
    } else {
        integrationMappings[campaignName] = updatedValues
        campaignMappings[integration] = integrationMappings
    }

    return campaignMappings
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
 * Get integrations where a campaign could be mapped.
 * A utm_campaign can only be mapped to ONE integration globally.
 * Returns empty array if already mapped to any integration.
 */
export function getAvailableIntegrationsForCampaign(
    utmCampaign: string,
    config: MarketingAnalyticsConfig | null
): NativeMarketingSource[] {
    if (!utmCampaign || getGlobalCampaignMapping(utmCampaign, config) !== null) {
        return []
    }
    return [...VALID_NATIVE_MARKETING_SOURCES]
}

export enum MappingTypes {
    Unmapped = 'unmapped',
    Default = 'default',
    Custom = 'custom',
}

export type SourceMappingStatus =
    | { type: MappingTypes.Unmapped }
    | { type: MappingTypes.Default; integration: NativeMarketingSource }
    | { type: MappingTypes.Custom; integration: NativeMarketingSource }

/**
 * Get detailed mapping status for a UTM source
 */
export function getSourceMappingStatus(
    utmSource: string,
    config: MarketingAnalyticsConfig | null
): SourceMappingStatus {
    if (!utmSource) {
        return { type: MappingTypes.Unmapped }
    }

    const normalizedSource = utmSource.toLowerCase().trim()

    // Check default mappings first
    for (const integration of VALID_NATIVE_MARKETING_SOURCES) {
        const defaults = MARKETING_DEFAULT_SOURCE_MAPPINGS[integration] || []
        if (defaults.some((d) => d.toLowerCase() === normalizedSource)) {
            return { type: MappingTypes.Default, integration }
        }
    }

    // Check custom mappings
    const customMappings = config?.custom_source_mappings || {}
    for (const [integration, sources] of Object.entries(customMappings)) {
        if ((sources as string[]).some((s) => s.toLowerCase() === normalizedSource)) {
            return { type: MappingTypes.Custom, integration: integration as NativeMarketingSource }
        }
    }

    return { type: MappingTypes.Unmapped }
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
