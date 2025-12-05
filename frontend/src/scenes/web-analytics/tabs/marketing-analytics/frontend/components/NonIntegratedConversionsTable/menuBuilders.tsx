import { IconChevronRight, IconTrash } from '@posthog/icons'

import { LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { IconLink } from 'lib/lemon-ui/icons'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { NativeMarketingSource } from '~/queries/schema/schema-general'

import { CampaignMappingInfo, MappingTypes, SourceMappingStatus } from './mappingUtils'

/** Maximum characters to show in menu titles before truncating */
const MENU_TITLE_MAX_LENGTH = 20
/** Maximum characters to show in row action labels before truncating */
const ROW_LABEL_MAX_LENGTH = 15

const DEFAULT_MATCHING_DISABLED_REASON = 'This matches a default mapping, so it cannot be modified.'
const getRemovingMappingLabel = (integration: string): string => `Remove mapping from ${integration}`
const getMapToLabel = (integration: string): string => `Map to ${integration}`
const MAPPING_LABEL = 'Mapping'
const getAlreadyMappedDisabledReason = (integration: string, campaignName: string): string =>
    `Already mapped to ${integration}: ${campaignName}`
const getLabel = (value: string, maxLength: number): string => `"${truncateWithEllipsis(value, maxLength)}"`
const getRowTitleLabel = (label: string, value: string): string => `${label}: ${getLabel(value, ROW_LABEL_MAX_LENGTH)}`
const getRemoveFromLabel = (integration: string, campaignName: string): string =>
    `Remove from ${integration}: ${campaignName}`

/** Truncates a string with ellipsis if it exceeds maxLength */
export function truncateWithEllipsis(value: string, maxLength: number): string {
    return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value
}

/** Source Menu Builder */
export interface SourceMenuBuilderParams {
    utmSource: string
    mappingStatus: SourceMappingStatus
    availableIntegrations: NativeMarketingSource[]
    onOpenIntegrationSettings?: (integration: NativeMarketingSource, utmValue: string) => void
    onRemoveMapping?: () => void
}

export function buildSourceMappingMenuItems({
    utmSource,
    mappingStatus,
    availableIntegrations,
    onOpenIntegrationSettings,
    onRemoveMapping,
}: SourceMenuBuilderParams): LemonMenuItems | null {
    // For default mappings, disable the entire Mapping menu
    if (mappingStatus.type === MappingTypes.Default) {
        return [
            {
                title: getLabel(utmSource, MENU_TITLE_MAX_LENGTH),
                items: [
                    {
                        label: MAPPING_LABEL,
                        icon: <IconLink />,
                        sideIcon: <IconChevronRight />,
                        disabledReason: DEFAULT_MATCHING_DISABLED_REASON,
                    },
                ],
            },
        ]
    }

    // Build mapping submenu items
    const mappingSubmenuItems: LemonMenuItem[] = []

    // If not mapped, show available integrations to map to
    if (mappingStatus.type === MappingTypes.Unmapped && availableIntegrations.length > 0) {
        availableIntegrations.forEach((integration) => {
            mappingSubmenuItems.push({
                label: getMapToLabel(integration),
                icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
                onClick: () => onOpenIntegrationSettings?.(integration, utmSource),
            })
        })
    }

    // If custom mapped, show remove option
    if (mappingStatus.type === MappingTypes.Custom) {
        mappingSubmenuItems.push({
            label: getRemovingMappingLabel(mappingStatus.integration),
            icon: <IconTrash />,
            status: 'danger' as const,
            onClick: onRemoveMapping,
        })
    }

    if (mappingSubmenuItems.length === 0) {
        return null
    }

    return [
        {
            title: getLabel(utmSource, MENU_TITLE_MAX_LENGTH),
            items: [
                {
                    label: MAPPING_LABEL,
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: mappingSubmenuItems,
                },
            ],
        },
    ]
}

/** Campaign Menu Builder */
export interface CampaignMenuBuilderParams {
    utmCampaign: string
    globalMapping: CampaignMappingInfo | null
    existingMappings: CampaignMappingInfo[]
    availableIntegrations: NativeMarketingSource[]
    onOpenIntegrationSettings?: (integration: NativeMarketingSource, utmValue: string) => void
    onRemoveMapping?: (integration: NativeMarketingSource, campaignName: string) => void
}

export function buildCampaignMappingMenuItems({
    utmCampaign,
    globalMapping,
    existingMappings,
    availableIntegrations,
    onOpenIntegrationSettings,
    onRemoveMapping,
}: CampaignMenuBuilderParams): LemonMenuItems | null {
    // If already mapped globally and no existing mappings to remove, show disabled state
    if (globalMapping && existingMappings.length === 0) {
        return [
            {
                title: getLabel(utmCampaign, MENU_TITLE_MAX_LENGTH),
                items: [
                    {
                        label: MAPPING_LABEL,
                        icon: <IconLink />,
                        sideIcon: <IconChevronRight />,
                        disabledReason: getAlreadyMappedDisabledReason(
                            globalMapping.integration,
                            globalMapping.campaignName
                        ),
                    },
                ],
            },
        ]
    }

    // Build mapping submenu items
    const mappingSubmenuItems: LemonMenuItem[] = []

    // If not mapped globally, show available integrations to map to
    if (availableIntegrations.length > 0) {
        availableIntegrations.forEach((integration) => {
            mappingSubmenuItems.push({
                label: getMapToLabel(integration),
                icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
                onClick: () => onOpenIntegrationSettings?.(integration, utmCampaign),
            })
        })
    }

    // If has existing mappings, show remove options
    if (existingMappings.length > 0) {
        existingMappings.forEach((mapping) => {
            mappingSubmenuItems.push({
                label: getRemoveFromLabel(mapping.integration, mapping.campaignName),
                icon: <IconTrash />,
                status: 'danger' as const,
                onClick: () => onRemoveMapping?.(mapping.integration, mapping.campaignName),
            })
        })
    }

    if (mappingSubmenuItems.length === 0) {
        return null
    }

    return [
        {
            title: getLabel(utmCampaign, MENU_TITLE_MAX_LENGTH),
            items: [
                {
                    label: MAPPING_LABEL,
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: mappingSubmenuItems,
                },
            ],
        },
    ]
}

/** Row Menu Builder */
export interface RowMenuBuilderParams {
    sourceValue: string
    campaignValue: string
    sourceMappingStatus: SourceMappingStatus
    availableSourceIntegrations: NativeMarketingSource[]
    globalCampaignMapping: CampaignMappingInfo | null
    existingCampaignMappings: CampaignMappingInfo[]
    availableCampaignIntegrations: NativeMarketingSource[]
    onOpenSourceSettings?: (integration: NativeMarketingSource, utmValue: string) => void
    onOpenCampaignSettings?: (integration: NativeMarketingSource, utmValue: string) => void
    onRemoveSourceMapping?: () => void
    onRemoveCampaignMapping?: (integration: NativeMarketingSource, campaignName: string) => void
}

export function buildRowMappingMenuItems({
    sourceValue,
    campaignValue,
    sourceMappingStatus,
    availableSourceIntegrations,
    globalCampaignMapping,
    existingCampaignMappings,
    availableCampaignIntegrations,
    onOpenSourceSettings,
    onOpenCampaignSettings,
    onRemoveSourceMapping,
    onRemoveCampaignMapping,
}: RowMenuBuilderParams): LemonMenuItems | null {
    // Build source mapping submenu
    const buildSourceItem = (): LemonMenuItem | null => {
        if (!sourceValue) {
            return null
        }

        // For default mappings, disable the entire menu
        if (sourceMappingStatus.type === MappingTypes.Default) {
            return {
                label: getRowTitleLabel('Source', sourceValue),
                icon: <IconLink />,
                disabledReason: DEFAULT_MATCHING_DISABLED_REASON,
            }
        }

        const submenuItems: LemonMenuItem[] = []

        // If not mapped, show available integrations
        if (sourceMappingStatus.type === MappingTypes.Unmapped && availableSourceIntegrations.length > 0) {
            availableSourceIntegrations.forEach((integration) => {
                submenuItems.push({
                    label: getMapToLabel(integration),
                    icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
                    onClick: () => onOpenSourceSettings?.(integration, sourceValue),
                })
            })
        }

        // If custom mapped, show remove option
        if (sourceMappingStatus.type === MappingTypes.Custom) {
            submenuItems.push({
                label: getRemovingMappingLabel(sourceMappingStatus.integration),
                icon: <IconTrash />,
                status: 'danger' as const,
                onClick: onRemoveSourceMapping,
            })
        }

        if (submenuItems.length === 0) {
            return null
        }

        return {
            label: getRowTitleLabel('Source', sourceValue),
            icon: <IconLink />,
            sideIcon: <IconChevronRight />,
            items: submenuItems,
        }
    }

    // Build campaign mapping submenu
    const buildCampaignItem = (): LemonMenuItem | null => {
        if (!campaignValue) {
            return null
        }

        // If already mapped globally and no existing mappings to remove, show disabled state
        if (globalCampaignMapping && existingCampaignMappings.length === 0) {
            return {
                label: getRowTitleLabel('Campaign', campaignValue),
                icon: <IconLink />,
                disabledReason: getAlreadyMappedDisabledReason(
                    globalCampaignMapping.integration,
                    globalCampaignMapping.campaignName
                ),
            }
        }

        const submenuItems: LemonMenuItem[] = []

        // If available integrations, show map options
        if (availableCampaignIntegrations.length > 0) {
            availableCampaignIntegrations.forEach((integration) => {
                submenuItems.push({
                    label: getMapToLabel(integration),
                    icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
                    onClick: () => onOpenCampaignSettings?.(integration, campaignValue),
                })
            })
        }

        // If has existing mappings, show remove options
        if (existingCampaignMappings.length > 0) {
            existingCampaignMappings.forEach((mapping) => {
                submenuItems.push({
                    label: getRemoveFromLabel(mapping.integration, mapping.campaignName),
                    icon: <IconTrash />,
                    status: 'danger' as const,
                    onClick: () => onRemoveCampaignMapping?.(mapping.integration, mapping.campaignName),
                })
            })
        }

        if (submenuItems.length === 0) {
            return null
        }

        return {
            label: getRowTitleLabel('Campaign', campaignValue),
            icon: <IconLink />,
            sideIcon: <IconChevronRight />,
            items: submenuItems,
        }
    }

    // Build the menu items
    const mappingItems: LemonMenuItem[] = []

    const sourceItem = buildSourceItem()
    if (sourceItem) {
        mappingItems.push(sourceItem)
    }

    const campaignItem = buildCampaignItem()
    if (campaignItem) {
        mappingItems.push(campaignItem)
    }

    if (mappingItems.length === 0) {
        return null
    }

    return [
        {
            title: MAPPING_LABEL,
            items: mappingItems,
        },
    ]
}
