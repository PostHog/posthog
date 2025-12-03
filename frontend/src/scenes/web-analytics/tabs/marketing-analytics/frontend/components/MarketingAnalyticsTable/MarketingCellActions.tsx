import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconChevronRight, IconTrash } from '@posthog/icons'

import { LemonMenuItem, LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'
import { IconLink } from 'lib/lemon-ui/icons'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { MarketingAnalyticsItem, NativeMarketingSource } from '~/queries/schema/schema-general'
import { CellActionProps, RowActionProps } from '~/queries/types'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { IntegrationSettingsModal, IntegrationSettingsTab } from '../settings/IntegrationSettingsModal'
import {
    CampaignMappingInfo,
    SourceMappingStatus,
    getAutoMatchedCampaigns,
    getAvailableIntegrationsForCampaign,
    getAvailableIntegrationsForSource,
    getCampaignMappings,
    getGlobalCampaignMapping,
    getSourceMappingStatus,
} from './marketingMappingUtils'

/** Maximum characters to show in menu titles before truncating */
const MENU_TITLE_MAX_LENGTH = 20
/** Maximum characters to show in row action labels before truncating */
const ROW_LABEL_MAX_LENGTH = 15

/** Truncates a string with ellipsis if it exceeds maxLength */
function truncateWithEllipsis(value: string, maxLength: number): string {
    return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value
}

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
        if (mappingStatus.type !== 'custom') {
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

    // For default mappings, disable the entire Mapping menu
    if (mappingStatus.type === 'default') {
        const menuItems: LemonMenuItems = [
            {
                title: `"${truncateWithEllipsis(utmSource, MENU_TITLE_MAX_LENGTH)}"`,
                items: [
                    {
                        label: 'Mapping',
                        icon: <IconLink />,
                        sideIcon: <IconChevronRight />,
                        disabledReason: 'This matches a default mapping, so it cannot be modified.',
                    },
                ],
            },
        ]
        return <LemonMenuOverlay items={menuItems} />
    }

    // Build mapping submenu items - either map to integration or remove existing mapping
    const mappingSubmenuItems: LemonMenuItem[] = []

    // If not mapped, show available integrations to map to
    if (mappingStatus.type === 'unmapped' && availableIntegrations.length > 0) {
        availableIntegrations.forEach((integration) => {
            mappingSubmenuItems.push({
                label: `Map to ${integration}`,
                icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
                onClick: () => onOpenIntegrationSettings?.(integration, utmSource),
            })
        })
    }

    // If custom mapped, show remove option
    if (mappingStatus.type === 'custom') {
        mappingSubmenuItems.push({
            label: `Remove mapping from ${mappingStatus.integration}`,
            icon: <IconTrash />,
            status: 'danger' as const,
            onClick: handleRemoveCustomMapping,
        })
    }

    if (mappingSubmenuItems.length === 0) {
        return null
    }

    // Build top-level menu with Mapping as parent
    const menuItems: LemonMenuItems = [
        {
            title: `"${truncateWithEllipsis(utmSource, MENU_TITLE_MAX_LENGTH)}"`,
            items: [
                {
                    label: 'Mapping',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: mappingSubmenuItems,
                },
            ],
        },
    ]

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
    // Note: getAvailableIntegrationsForCampaign already returns empty if globally mapped
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

    // If already mapped globally and no existing mappings to remove, show disabled state
    if (globalMapping && existingMappings.length === 0) {
        const menuItems: LemonMenuItems = [
            {
                title: `"${truncateWithEllipsis(utmCampaign, MENU_TITLE_MAX_LENGTH)}"`,
                items: [
                    {
                        label: 'Mapping',
                        icon: <IconLink />,
                        sideIcon: <IconChevronRight />,
                        disabledReason: `Already mapped to ${globalMapping.integration}: ${globalMapping.campaignName}`,
                    },
                ],
            },
        ]
        return <LemonMenuOverlay items={menuItems} />
    }

    // Build mapping submenu items - either map to integration or remove existing mappings
    const mappingSubmenuItems: LemonMenuItem[] = []

    // If not mapped globally, show available integrations to map to
    if (availableIntegrations.length > 0) {
        availableIntegrations.forEach((integration) => {
            mappingSubmenuItems.push({
                label: `Map to ${integration}`,
                icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
                onClick: () => onOpenIntegrationSettings?.(integration, utmCampaign),
            })
        })
    }

    // If has existing mappings, show remove options
    if (existingMappings.length > 0) {
        existingMappings.forEach((mapping) => {
            mappingSubmenuItems.push({
                label: `Remove from ${mapping.integration}: ${mapping.campaignName}`,
                icon: <IconTrash />,
                status: 'danger' as const,
                onClick: () => handleRemoveCampaignMapping(mapping.integration, mapping.campaignName),
            })
        })
    }

    if (mappingSubmenuItems.length === 0) {
        return null
    }

    // Build top-level menu with Mapping as parent
    const menuItems: LemonMenuItems = [
        {
            title: `"${truncateWithEllipsis(utmCampaign, MENU_TITLE_MAX_LENGTH)}"`,
            items: [
                {
                    label: 'Mapping',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: mappingSubmenuItems,
                },
            ],
        },
    ]

    return <LemonMenuOverlay items={menuItems} />
}

interface IntegrationSettingsModalState {
    isOpen: boolean
    integration: NativeMarketingSource | null
    initialTab: IntegrationSettingsTab
    initialUtmValue: string
}

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
        if (sourceMappingStatus.type !== 'custom') {
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

    // Build source mapping submenu
    const buildSourceMappingItems = (): LemonMenuItem | null => {
        if (!sourceValue) {
            return null
        }

        // For default mappings, disable the entire menu
        if (sourceMappingStatus.type === 'default') {
            return {
                label: `Source: "${truncateWithEllipsis(sourceValue, ROW_LABEL_MAX_LENGTH)}"`,
                icon: <IconLink />,
                disabledReason: 'This matches a default mapping, so it cannot be modified.',
            }
        }

        const submenuItems: LemonMenuItem[] = []

        // If not mapped, show available integrations
        if (sourceMappingStatus.type === 'unmapped' && availableSourceIntegrations.length > 0) {
            availableSourceIntegrations.forEach((integration) => {
                submenuItems.push({
                    label: `Map to ${integration}`,
                    icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
                    onClick: () => onOpenSourceSettings?.(integration, sourceValue),
                })
            })
        }

        // If custom mapped, show remove option
        if (sourceMappingStatus.type === 'custom') {
            submenuItems.push({
                label: `Remove mapping from ${sourceMappingStatus.integration}`,
                icon: <IconTrash />,
                status: 'danger' as const,
                onClick: handleRemoveSourceMapping,
            })
        }

        if (submenuItems.length === 0) {
            return null
        }

        return {
            label: `Source: "${truncateWithEllipsis(sourceValue, ROW_LABEL_MAX_LENGTH)}"`,
            icon: <IconLink />,
            sideIcon: <IconChevronRight />,
            items: submenuItems,
        }
    }

    // Build campaign mapping submenu
    const buildCampaignMappingItems = (): LemonMenuItem | null => {
        if (!campaignValue) {
            return null
        }

        // If already mapped globally and no existing mappings to remove, show disabled state
        if (globalCampaignMapping && existingCampaignMappings.length === 0) {
            return {
                label: `Campaign: "${truncateWithEllipsis(campaignValue, ROW_LABEL_MAX_LENGTH)}"`,
                icon: <IconLink />,
                disabledReason: `Already mapped to ${globalCampaignMapping.integration}: ${globalCampaignMapping.campaignName}`,
            }
        }

        const submenuItems: LemonMenuItem[] = []

        // If available integrations, show map options
        if (availableCampaignIntegrations.length > 0) {
            availableCampaignIntegrations.forEach((integration) => {
                submenuItems.push({
                    label: `Map to ${integration}`,
                    icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
                    onClick: () => onOpenCampaignSettings?.(integration, campaignValue),
                })
            })
        }

        // If has existing mappings, show remove options
        if (existingCampaignMappings.length > 0) {
            existingCampaignMappings.forEach((mapping) => {
                submenuItems.push({
                    label: `Remove from ${mapping.integration}: ${mapping.campaignName}`,
                    icon: <IconTrash />,
                    status: 'danger' as const,
                    onClick: () => handleRemoveCampaignMapping(mapping.integration, mapping.campaignName),
                })
            })
        }

        if (submenuItems.length === 0) {
            return null
        }

        return {
            label: `Campaign: "${truncateWithEllipsis(campaignValue, ROW_LABEL_MAX_LENGTH)}"`,
            icon: <IconLink />,
            sideIcon: <IconChevronRight />,
            items: submenuItems,
        }
    }

    // Build the menu items
    const mappingItems: LemonMenuItem[] = []

    const sourceItem = buildSourceMappingItems()
    if (sourceItem) {
        mappingItems.push(sourceItem)
    }

    const campaignItem = buildCampaignMappingItems()
    if (campaignItem) {
        mappingItems.push(campaignItem)
    }

    if (mappingItems.length === 0) {
        return null
    }

    const menuItems: LemonMenuItems = [
        {
            title: 'Mapping',
            items: mappingItems,
        },
    ]

    return <LemonMenuOverlay items={menuItems} />
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
