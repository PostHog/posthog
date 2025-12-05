import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import { MarketingAnalyticsItem, NativeMarketingSource } from '~/queries/schema/schema-general'
import { CellActionProps, RowActionProps } from '~/queries/types'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { IntegrationSettingsModal, IntegrationSettingsTab } from '../settings/IntegrationSettingsModal'
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
} from './marketingMappingUtils'
import {
    buildCampaignMappingMenuItems,
    buildRowMappingMenuItems,
    buildSourceMappingMenuItems,
} from './marketingMenuBuilders'

/**
 * Extract the string value from a cell value.
 * In Marketing Analytics, values are MarketingAnalyticsItem objects.
 */
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

/** Cell Action Components */
export interface MapSourceCellActionsProps extends CellActionProps {
    onOpenIntegrationSettings?: (integration: NativeMarketingSource, utmValue: string) => void
}

export function MapSourceCellActions({
    value,
    onOpenIntegrationSettings,
}: MapSourceCellActionsProps): JSX.Element | null {
    const { marketingAnalyticsConfig, integrationCampaignTables } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCustomSourceMappings } = useActions(marketingAnalyticsSettingsLogic)

    const utmSource = extractStringValue(value)

    if (!utmSource) {
        return null
    }

    const mappingStatus: SourceMappingStatus = getSourceMappingStatus(utmSource, marketingAnalyticsConfig)

    // Get available integrations for mapping (only those with data)
    const availableIntegrations = getAvailableIntegrationsForSource(utmSource, marketingAnalyticsConfig).filter(
        (integration) => !!integrationCampaignTables[integration]
    )

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
        onOpenIntegrationSettings,
        onRemoveMapping: handleRemoveCustomMapping,
    })

    if (!menuItems) {
        return null
    }

    return <LemonMenuOverlay items={menuItems} />
}

export interface MapCampaignCellActionsProps extends CellActionProps {
    onOpenIntegrationSettings?: (integration: NativeMarketingSource, utmValue: string) => void
}

export function MapCampaignCellActions({
    value,
    onOpenIntegrationSettings,
}: MapCampaignCellActionsProps): JSX.Element | null {
    const { marketingAnalyticsConfig, integrationCampaignTables, integrationCampaigns } = useValues(
        marketingAnalyticsSettingsLogic
    )
    const { updateCampaignNameMappings } = useActions(marketingAnalyticsSettingsLogic)

    const utmCampaign = extractStringValue(value)

    if (!utmCampaign) {
        return null
    }

    // Check if this utm_campaign is already mapped globally (can only be in one mapping)
    const globalMapping = getGlobalCampaignMapping(utmCampaign, marketingAnalyticsConfig)

    // Get auto-matched campaigns (campaigns that match integration data directly)
    const autoMatched = getAutoMatchedCampaigns(utmCampaign, integrationCampaigns, marketingAnalyticsConfig)
    const autoMatchedIntegrations = new Set(autoMatched.map((m) => m.integration))

    // Get existing manual mappings for this campaign
    const existingMappings: CampaignMappingInfo[] = getCampaignMappings(utmCampaign, marketingAnalyticsConfig)

    // Get available integrations for new mappings (only those with data and not auto-matched)
    const availableIntegrations = getAvailableIntegrationsForCampaign(utmCampaign, marketingAnalyticsConfig).filter(
        (integration) => !!integrationCampaignTables[integration] && !autoMatchedIntegrations.has(integration)
    )

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
        onOpenIntegrationSettings,
        onRemoveMapping: handleRemoveCampaignMapping,
    })

    if (!menuItems) {
        return null
    }

    return <LemonMenuOverlay items={menuItems} />
}

/** Row Action Component */
export interface MarketingRowActionsProps extends RowActionProps {
    onOpenSourceSettings?: (integration: NativeMarketingSource, utmValue: string) => void
    onOpenCampaignSettings?: (integration: NativeMarketingSource, utmValue: string) => void
}

export function MarketingRowActions({
    record,
    onOpenSourceSettings,
    onOpenCampaignSettings,
}: MarketingRowActionsProps): JSX.Element | null {
    const { marketingAnalyticsConfig, integrationCampaignTables, integrationCampaigns } = useValues(
        marketingAnalyticsSettingsLogic
    )
    const { updateCustomSourceMappings, updateCampaignNameMappings } = useActions(marketingAnalyticsSettingsLogic)

    // Extract source and campaign values from the row
    const rowData = record.result as unknown[]
    if (!rowData || !Array.isArray(rowData)) {
        return null
    }

    // Find the source and campaign column indices
    const sourceIndex = 0 // Source is always first column
    const campaignIndex = 1 // Campaign is always second column

    const sourceValue = extractStringValue(rowData[sourceIndex])
    const campaignValue = extractStringValue(rowData[campaignIndex])

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

    // Handle source mapping removal
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

    // Handle campaign mapping removal
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
        onOpenSourceSettings,
        onOpenCampaignSettings,
        onRemoveSourceMapping: handleRemoveSourceMapping,
        onRemoveCampaignMapping: handleRemoveCampaignMapping,
    })

    if (!menuItems) {
        return null
    }

    return <LemonMenuOverlay items={menuItems} />
}

/** Hook for using cell actions with modal */
interface IntegrationSettingsModalState {
    isOpen: boolean
    integration: NativeMarketingSource | null
    initialTab: IntegrationSettingsTab
    initialUtmValue: string
}

export interface UseMarketingCellActionsReturn {
    sourceActions: (props: CellActionProps) => JSX.Element | null
    campaignActions: (props: CellActionProps) => JSX.Element | null
    rowActions: (props: RowActionProps) => JSX.Element | null
    integrationSettingsModal: JSX.Element | null
}

export function useMarketingCellActions(): UseMarketingCellActionsReturn {
    const [modalState, setModalState] = useState<IntegrationSettingsModalState>({
        isOpen: false,
        integration: null,
        initialTab: 'mappings',
        initialUtmValue: '',
    })

    const handleOpenCampaignSettings = useCallback((integration: NativeMarketingSource, utmValue: string) => {
        setModalState({
            isOpen: true,
            integration,
            initialTab: 'mappings',
            initialUtmValue: utmValue,
        })
    }, [])

    const handleOpenSourceSettings = useCallback((integration: NativeMarketingSource, utmValue: string) => {
        setModalState({
            isOpen: true,
            integration,
            initialTab: 'sources',
            initialUtmValue: utmValue,
        })
    }, [])

    const handleCloseModal = useCallback(() => {
        setModalState({
            isOpen: false,
            integration: null,
            initialTab: 'mappings',
            initialUtmValue: '',
        })
    }, [])

    const sourceActions = useCallback(
        (props: CellActionProps) => (
            <MapSourceCellActions {...props} onOpenIntegrationSettings={handleOpenSourceSettings} />
        ),
        [handleOpenSourceSettings]
    )

    const campaignActions = useCallback(
        (props: CellActionProps) => (
            <MapCampaignCellActions {...props} onOpenIntegrationSettings={handleOpenCampaignSettings} />
        ),
        [handleOpenCampaignSettings]
    )

    const rowActions = useCallback(
        (props: RowActionProps) => (
            <MarketingRowActions
                {...props}
                onOpenSourceSettings={handleOpenSourceSettings}
                onOpenCampaignSettings={handleOpenCampaignSettings}
            />
        ),
        [handleOpenSourceSettings, handleOpenCampaignSettings]
    )

    const integrationSettingsModal = modalState.integration ? (
        <IntegrationSettingsModal
            integrationName={modalState.integration}
            isOpen={modalState.isOpen}
            onClose={handleCloseModal}
            initialTab={modalState.initialTab}
            initialUtmValue={modalState.initialUtmValue}
        />
    ) : null

    return {
        sourceActions,
        campaignActions,
        rowActions,
        integrationSettingsModal,
    }
}
