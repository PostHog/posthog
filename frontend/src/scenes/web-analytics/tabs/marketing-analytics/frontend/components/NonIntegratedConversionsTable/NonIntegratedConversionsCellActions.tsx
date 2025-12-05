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
import {
    buildCampaignMappingMenuItems,
    buildSourceMappingMenuItems,
} from '../MarketingAnalyticsTable/marketingMenuBuilders'

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

    const mappingStatus: SourceMappingStatus = getSourceMappingStatus(utmSource, marketingAnalyticsConfig)

    const availableIntegrations = getAvailableIntegrationsForSource(utmSource, marketingAnalyticsConfig).filter(
        (integration) => !!integrationCampaignTables[integration]
    )

    const handleOpenSettings = (integration: NativeMarketingSource, utmValue: string): void => {
        openIntegrationSettingsModal(integration, 'sources', utmValue)
    }

    const handleRemoveCustomMapping = (): void => {
        if (mappingStatus.type !== MappingTypes.Custom) {
            return
        }
        const customMappings = { ...marketingAnalyticsConfig?.custom_source_mappings }
        const integrationSources = [...(customMappings[mappingStatus.integration] || [])]
        const updatedSources = integrationSources.filter((s) => s.toLowerCase() !== utmSource.toLowerCase())

        if (updatedSources.length === 0) {
            delete customMappings[mappingStatus.integration]
        } else {
            customMappings[mappingStatus.integration] = updatedSources
        }

        updateCustomSourceMappings(customMappings)
    }

    const menuItems = buildSourceMappingMenuItems({
        utmSource,
        mappingStatus,
        availableIntegrations,
        onOpenIntegrationSettings: handleOpenSettings,
        onRemoveMapping: handleRemoveCustomMapping,
    })

    if (!menuItems) {
        return null
    }

    return <LemonMenuOverlay items={menuItems} />
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
    const existingMappings: CampaignMappingInfo[] = getCampaignMappings(utmCampaign, marketingAnalyticsConfig)
    const availableIntegrations = getAvailableIntegrationsForCampaign(utmCampaign, marketingAnalyticsConfig).filter(
        (integration) => !!integrationCampaignTables[integration] && !autoMatchedIntegrations.has(integration)
    )

    const handleOpenSettings = (integration: NativeMarketingSource, utmValue: string): void => {
        openIntegrationSettingsModal(integration, 'mappings', utmValue)
    }

    const handleRemoveCampaignMapping = (integration: NativeMarketingSource, campaignName: string): void => {
        const campaignMappings = { ...marketingAnalyticsConfig?.campaign_name_mappings }
        const integrationMappings = { ...campaignMappings[integration] }
        const currentValues = [...(integrationMappings[campaignName] || [])]
        const updatedValues = currentValues.filter((v) => v.toLowerCase() !== utmCampaign.toLowerCase())

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

    const menuItems = buildCampaignMappingMenuItems({
        utmCampaign,
        globalMapping,
        existingMappings,
        availableIntegrations,
        onOpenIntegrationSettings: handleOpenSettings,
        onRemoveMapping: handleRemoveCampaignMapping,
    })

    if (!menuItems) {
        return null
    }

    return <LemonMenuOverlay items={menuItems} />
}
