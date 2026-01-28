import { IconChevronRight, IconTrash } from '@posthog/icons'

import { LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { IconLink } from 'lib/lemon-ui/icons'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { NativeMarketingSource } from '~/queries/schema/schema-general'

import { CampaignMappingInfo, MappingTypes, SourceMappingStatus } from './mappingUtils'

const MENU_TITLE_MAX_LENGTH = 20
const ROW_LABEL_MAX_LENGTH = 15
const DEFAULT_MATCHING_DISABLED_REASON = 'This matches a default mapping, so it cannot be modified.'
const MAPPING_LABEL = 'Mapping'

function truncateWithEllipsis(value: string, maxLength: number): string {
    return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value
}

function formatLabel(value: string, maxLength: number): string {
    return `"${truncateWithEllipsis(value, maxLength)}"`
}

/** Create menu items for mapping to available integrations */
function createMapToItems(
    integrations: NativeMarketingSource[],
    utmValue: string,
    onOpenSettings?: (integration: NativeMarketingSource, utmValue: string) => void
): LemonMenuItem[] {
    return integrations.map((integration) => ({
        label: `Map to ${integration}`,
        icon: <DataWarehouseSourceIcon type={integration} size="xsmall" disableTooltip />,
        onClick: () => onOpenSettings?.(integration, utmValue),
    }))
}

/** Create menu item for removing a source mapping */
function createRemoveSourceItem(integration: NativeMarketingSource, onRemove?: () => void): LemonMenuItem {
    return {
        label: `Remove mapping from ${integration}`,
        icon: <IconTrash />,
        status: 'danger' as const,
        onClick: onRemove,
    }
}

/** Create menu items for removing campaign mappings */
function createRemoveCampaignItems(
    mappings: CampaignMappingInfo[],
    onRemove?: (integration: NativeMarketingSource, campaignName: string) => void
): LemonMenuItem[] {
    return mappings.map((mapping) => ({
        label: `Remove from ${mapping.integration}: ${mapping.campaignName}`,
        icon: <IconTrash />,
        status: 'danger' as const,
        onClick: () => onRemove?.(mapping.integration, mapping.campaignName),
    }))
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
    const title = formatLabel(utmSource, MENU_TITLE_MAX_LENGTH)

    if (mappingStatus.type === MappingTypes.Default) {
        return [
            {
                title,
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

    const submenuItems: LemonMenuItem[] = []

    if (mappingStatus.type === MappingTypes.Unmapped) {
        submenuItems.push(...createMapToItems(availableIntegrations, utmSource, onOpenIntegrationSettings))
    }

    if (mappingStatus.type === MappingTypes.Custom) {
        submenuItems.push(createRemoveSourceItem(mappingStatus.integration, onRemoveMapping))
    }

    if (submenuItems.length === 0) {
        return null
    }

    return [
        {
            title,
            items: [
                {
                    label: MAPPING_LABEL,
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: submenuItems,
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
    const title = formatLabel(utmCampaign, MENU_TITLE_MAX_LENGTH)

    if (globalMapping && existingMappings.length === 0) {
        return [
            {
                title,
                items: [
                    {
                        label: MAPPING_LABEL,
                        icon: <IconLink />,
                        sideIcon: <IconChevronRight />,
                        disabledReason: `Already mapped to ${globalMapping.integration}: ${globalMapping.campaignName}`,
                    },
                ],
            },
        ]
    }

    const submenuItems: LemonMenuItem[] = [
        ...createMapToItems(availableIntegrations, utmCampaign, onOpenIntegrationSettings),
        ...createRemoveCampaignItems(existingMappings, onRemoveMapping),
    ]

    if (submenuItems.length === 0) {
        return null
    }

    return [
        {
            title,
            items: [
                {
                    label: MAPPING_LABEL,
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: submenuItems,
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
    const mappingItems: LemonMenuItem[] = []

    // Build source item
    if (sourceValue) {
        const sourceLabel = `Source: ${formatLabel(sourceValue, ROW_LABEL_MAX_LENGTH)}`

        if (sourceMappingStatus.type === MappingTypes.Default) {
            mappingItems.push({
                label: sourceLabel,
                icon: <IconLink />,
                disabledReason: DEFAULT_MATCHING_DISABLED_REASON,
            })
        } else {
            const sourceSubmenuItems: LemonMenuItem[] = []

            if (sourceMappingStatus.type === MappingTypes.Unmapped) {
                sourceSubmenuItems.push(
                    ...createMapToItems(availableSourceIntegrations, sourceValue, onOpenSourceSettings)
                )
            }

            if (sourceMappingStatus.type === MappingTypes.Custom) {
                sourceSubmenuItems.push(createRemoveSourceItem(sourceMappingStatus.integration, onRemoveSourceMapping))
            }

            if (sourceSubmenuItems.length > 0) {
                mappingItems.push({
                    label: sourceLabel,
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: sourceSubmenuItems,
                })
            }
        }
    }

    // Build campaign item
    if (campaignValue) {
        const campaignLabel = `Campaign: ${formatLabel(campaignValue, ROW_LABEL_MAX_LENGTH)}`

        if (globalCampaignMapping && existingCampaignMappings.length === 0) {
            mappingItems.push({
                label: campaignLabel,
                icon: <IconLink />,
                disabledReason: `Already mapped to ${globalCampaignMapping.integration}: ${globalCampaignMapping.campaignName}`,
            })
        } else {
            const campaignSubmenuItems: LemonMenuItem[] = [
                ...createMapToItems(availableCampaignIntegrations, campaignValue, onOpenCampaignSettings),
                ...createRemoveCampaignItems(existingCampaignMappings, onRemoveCampaignMapping),
            ]

            if (campaignSubmenuItems.length > 0) {
                mappingItems.push({
                    label: campaignLabel,
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: campaignSubmenuItems,
                })
            }
        }
    }

    if (mappingItems.length === 0) {
        return null
    }

    return [{ title: MAPPING_LABEL, items: mappingItems }]
}
