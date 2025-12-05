import { useActions, useValues } from 'kea'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import { MarketingAnalyticsItem, NativeMarketingSource } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    CampaignMappingInfo,
    MappingTypes,
    SourceMappingStatus,
    getAutoMatchedCampaigns,
    getAvailableIntegrationsForCampaign,
    getAvailableIntegrationsForSource,
    getCampaignMappings,
    getGlobalCampaignMapping,
    getSourceMappingStatus,
} from '../MarketingAnalyticsTable/marketingMappingUtils'
import { buildRowMappingMenuItems } from '../MarketingAnalyticsTable/marketingMenuBuilders'

function extractStringValue(value: unknown): string {
    if (value == null) {
        return ''
    }
    if (typeof value === 'object' && 'value' in value) {
        const item = value as MarketingAnalyticsItem
        return String(item.value ?? '').trim()
    }
    return String(value).trim()
}

export interface NonIntegratedConversionsRowActionsProps {
    result: Record<string, any> | any[]
    columnsInResponse: string[]
}

export function NonIntegratedConversionsRowActions({
    result,
    columnsInResponse,
}: NonIntegratedConversionsRowActionsProps): JSX.Element | null {
    const { marketingAnalyticsConfig, integrationCampaignTables, integrationCampaigns } = useValues(
        marketingAnalyticsSettingsLogic
    )
    const { updateCustomSourceMappings, updateCampaignNameMappings, openIntegrationSettingsModal } = useActions(
        marketingAnalyticsSettingsLogic
    )

    // Ensure result is an array
    if (!Array.isArray(result)) {
        return null
    }

    // Find source and campaign column indices
    const sourceIndex = columnsInResponse.findIndex((col) => col.toLowerCase() === 'source')
    const campaignIndex = columnsInResponse.findIndex((col) => col.toLowerCase() === 'campaign')

    const sourceValue = sourceIndex >= 0 ? extractStringValue(result[sourceIndex]) : ''
    const campaignValue = campaignIndex >= 0 ? extractStringValue(result[campaignIndex]) : ''

    if (!sourceValue && !campaignValue) {
        return null
    }

    // Get source mapping info
    const sourceMappingStatus: SourceMappingStatus = getSourceMappingStatus(sourceValue, marketingAnalyticsConfig)
    const availableSourceIntegrations = getAvailableIntegrationsForSource(sourceValue, marketingAnalyticsConfig).filter(
        (integration) => !!integrationCampaignTables[integration]
    )

    // Get campaign mapping info
    const globalCampaignMapping = getGlobalCampaignMapping(campaignValue, marketingAnalyticsConfig)
    const autoMatchedCampaigns = getAutoMatchedCampaigns(campaignValue, integrationCampaigns, marketingAnalyticsConfig)
    const autoMatchedIntegrations = new Set(autoMatchedCampaigns.map((m) => m.integration))
    const existingCampaignMappings: CampaignMappingInfo[] = getCampaignMappings(campaignValue, marketingAnalyticsConfig)
    const availableCampaignIntegrations = getAvailableIntegrationsForCampaign(
        campaignValue,
        marketingAnalyticsConfig
    ).filter((integration) => !!integrationCampaignTables[integration] && !autoMatchedIntegrations.has(integration))

    const handleOpenSourceSettings = (integration: NativeMarketingSource, utmValue: string): void => {
        openIntegrationSettingsModal(integration, 'sources', utmValue)
    }

    const handleOpenCampaignSettings = (integration: NativeMarketingSource, utmValue: string): void => {
        openIntegrationSettingsModal(integration, 'mappings', utmValue)
    }

    const handleRemoveSourceMapping = (): void => {
        if (sourceMappingStatus.type !== MappingTypes.Custom) {
            return
        }
        const customMappings = { ...marketingAnalyticsConfig?.custom_source_mappings }
        const integrationSources = [...(customMappings[sourceMappingStatus.integration] || [])]
        const updatedSources = integrationSources.filter((s) => s.toLowerCase() !== sourceValue.toLowerCase())

        if (updatedSources.length === 0) {
            delete customMappings[sourceMappingStatus.integration]
        } else {
            customMappings[sourceMappingStatus.integration] = updatedSources
        }

        updateCustomSourceMappings(customMappings)
    }

    const handleRemoveCampaignMapping = (integration: NativeMarketingSource, campaignName: string): void => {
        const campaignMappings = { ...marketingAnalyticsConfig?.campaign_name_mappings }
        const integrationMappings = { ...campaignMappings[integration] }
        const currentValues = [...(integrationMappings[campaignName] || [])]
        const updatedValues = currentValues.filter((v) => v.toLowerCase() !== campaignValue.toLowerCase())

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

        updateCampaignNameMappings(campaignMappings)
    }

    const menuItems = buildRowMappingMenuItems({
        sourceValue,
        campaignValue,
        sourceMappingStatus,
        availableSourceIntegrations,
        globalCampaignMapping,
        existingCampaignMappings,
        availableCampaignIntegrations,
        onOpenSourceSettings: handleOpenSourceSettings,
        onOpenCampaignSettings: handleOpenCampaignSettings,
        onRemoveSourceMapping: handleRemoveSourceMapping,
        onRemoveCampaignMapping: handleRemoveCampaignMapping,
    })

    if (!menuItems) {
        return null
    }

    return <LemonMenuOverlay items={menuItems} />
}
