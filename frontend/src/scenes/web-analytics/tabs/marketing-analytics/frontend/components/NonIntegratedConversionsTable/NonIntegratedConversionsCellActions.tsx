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
import { buildCampaignMappingMenuItems, buildSourceMappingMenuItems } from './menuBuilders'

export interface NonIntegratedConversionsCellActionsProps {
    columnName: string
    value: unknown
}

export function NonIntegratedConversionsCellActions({
    columnName,
    value,
}: NonIntegratedConversionsCellActionsProps): JSX.Element | null {
    const columnLower = columnName.toLowerCase()

    if (columnLower === 'source') {
        return <SourceCellActions value={value} />
    }

    if (columnLower === 'campaign') {
        return <CampaignCellActions value={value} />
    }

    return null
}

function SourceCellActions({ value }: { value: unknown }): JSX.Element | null {
    const { marketingAnalyticsConfig, integrationCampaignTables } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCustomSourceMappings, openIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)

    const utmSource = extractStringValue(value)
    if (!utmSource) {
        return null
    }

    const mappingStatus = getSourceMappingStatus(utmSource, marketingAnalyticsConfig)
    const availableIntegrations = getAvailableIntegrationsForSource(utmSource, marketingAnalyticsConfig).filter(
        (integration) => !!integrationCampaignTables[integration]
    )

    const menuItems = buildSourceMappingMenuItems({
        utmSource,
        mappingStatus,
        availableIntegrations,
        onOpenIntegrationSettings: (integration: NativeMarketingSource, utmValue: string) => {
            openIntegrationSettingsModal(integration, 'sources', utmValue)
        },
        onRemoveMapping:
            mappingStatus.type === MappingTypes.Custom
                ? () => {
                      updateCustomSourceMappings(
                          removeSourceFromMappings(marketingAnalyticsConfig, mappingStatus.integration, utmSource)
                      )
                  }
                : undefined,
    })

    return menuItems ? <LemonMenuOverlay items={menuItems} /> : null
}

function CampaignCellActions({ value }: { value: unknown }): JSX.Element | null {
    const { marketingAnalyticsConfig, integrationCampaignTables, integrationCampaigns } = useValues(
        marketingAnalyticsSettingsLogic
    )
    const { updateCampaignNameMappings, openIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)

    const utmCampaign = extractStringValue(value)
    if (!utmCampaign) {
        return null
    }

    const globalMapping = getGlobalCampaignMapping(utmCampaign, marketingAnalyticsConfig)
    const autoMatched = getAutoMatchedCampaigns(utmCampaign, integrationCampaigns, marketingAnalyticsConfig)
    const autoMatchedIntegrations = new Set(autoMatched.map((m) => m.integration))
    const existingMappings = getCampaignMappings(utmCampaign, marketingAnalyticsConfig)
    const availableIntegrations = getAvailableIntegrationsForCampaign(utmCampaign, marketingAnalyticsConfig).filter(
        (integration) => !!integrationCampaignTables[integration] && !autoMatchedIntegrations.has(integration)
    )

    const menuItems = buildCampaignMappingMenuItems({
        utmCampaign,
        globalMapping,
        existingMappings,
        availableIntegrations,
        onOpenIntegrationSettings: (integration: NativeMarketingSource, utmValue: string) => {
            openIntegrationSettingsModal(integration, 'mappings', utmValue)
        },
        onRemoveMapping: (integration: NativeMarketingSource, campaignName: string) => {
            updateCampaignNameMappings(
                removeCampaignFromMappings(marketingAnalyticsConfig, integration, campaignName, utmCampaign)
            )
        },
    })

    return menuItems ? <LemonMenuOverlay items={menuItems} /> : null
}
