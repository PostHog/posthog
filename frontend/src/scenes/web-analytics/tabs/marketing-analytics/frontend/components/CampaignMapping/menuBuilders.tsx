import { IconChevronRight, IconTrash } from '@posthog/icons'

import { IconLink } from 'lib/lemon-ui/icons'
import { LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { NativeMarketingSource } from '~/queries/schema/schema-general'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { CampaignMappingInfo, MappingTypes, SourceMappingStatus } from './mappingUtils'

const MENU_TITLE_MAX_LENGTH = 20
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
        icon: <SourceIcon type={integration} size="xsmall" disableTooltip />,
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
