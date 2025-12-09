import { useActions, useValues } from 'kea'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import { NativeMarketingSource } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    MappingTypes,
    extractStringValue,
    getAutoMatchedCampaigns,
    getAvailableIntegrationsForCampaign,
    getAvailableIntegrationsForSource,
    getCampaignMappings,
    getGlobalCampaignMapping,
    getSourceMappingStatus,
    removeCampaignFromMappings,
    removeSourceFromMappings,
} from './mappingUtils'
import { buildRowMappingMenuItems } from './menuBuilders'

export interface NonIntegratedConversionsRowActionsProps {
    result: Record<string, unknown> | unknown[]
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
    const sourceMappingStatus = getSourceMappingStatus(sourceValue, marketingAnalyticsConfig)
    const availableSourceIntegrations = getAvailableIntegrationsForSource(sourceValue, marketingAnalyticsConfig).filter(
        (integration) => !!integrationCampaignTables[integration]
    )

    // Get campaign mapping info
    const globalCampaignMapping = getGlobalCampaignMapping(campaignValue, marketingAnalyticsConfig)
    const autoMatchedCampaigns = getAutoMatchedCampaigns(campaignValue, integrationCampaigns, marketingAnalyticsConfig)
    const autoMatchedIntegrations = new Set(autoMatchedCampaigns.map((m) => m.integration))
    const existingCampaignMappings = getCampaignMappings(campaignValue, marketingAnalyticsConfig)
    const availableCampaignIntegrations = getAvailableIntegrationsForCampaign(
        campaignValue,
        marketingAnalyticsConfig
    ).filter((integration) => !!integrationCampaignTables[integration] && !autoMatchedIntegrations.has(integration))

    const menuItems = buildRowMappingMenuItems({
        sourceValue,
        campaignValue,
        sourceMappingStatus,
        availableSourceIntegrations,
        globalCampaignMapping,
        existingCampaignMappings,
        availableCampaignIntegrations,
        onOpenSourceSettings: (integration: NativeMarketingSource, utmValue: string) => {
            openIntegrationSettingsModal(integration, 'sources', utmValue)
        },
        onOpenCampaignSettings: (integration: NativeMarketingSource, utmValue: string) => {
            openIntegrationSettingsModal(integration, 'mappings', utmValue)
        },
        onRemoveSourceMapping:
            sourceMappingStatus.type === MappingTypes.Custom
                ? () => {
                      updateCustomSourceMappings(
                          removeSourceFromMappings(
                              marketingAnalyticsConfig,
                              sourceMappingStatus.integration,
                              sourceValue
                          )
                      )
                  }
                : undefined,
        onRemoveCampaignMapping: (integration: NativeMarketingSource, campaignName: string) => {
            updateCampaignNameMappings(
                removeCampaignFromMappings(marketingAnalyticsConfig, integration, campaignName, campaignValue)
            )
        },
    })

    return menuItems ? <LemonMenuOverlay items={menuItems} /> : null
}
