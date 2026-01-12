import { Meta, StoryFn } from '@storybook/react'

import { LemonMenuItem, LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import { mswDecorator } from '~/mocks/browser'
import { VALID_NATIVE_MARKETING_SOURCES } from '~/queries/schema/schema-general'

import { MappingTypes } from './mappingUtils'
import { buildCampaignMappingMenuItems, buildRowMappingMenuItems, buildSourceMappingMenuItems } from './menuBuilders'

// Mock icons for marketing sources - these are the paths returned by the backend
const MARKETING_SOURCE_ICONS: Record<string, { name: string; iconPath: string; fields: never[]; caption: string }> = {
    GoogleAds: {
        name: 'GoogleAds',
        iconPath: '/static/services/google-ads.png',
        fields: [],
        caption: 'Google Ads',
    },
    MetaAds: {
        name: 'MetaAds',
        iconPath: '/static/services/meta-ads.png',
        fields: [],
        caption: 'Meta Ads',
    },
    LinkedinAds: {
        name: 'LinkedinAds',
        iconPath: '/static/services/linkedin.png',
        fields: [],
        caption: 'LinkedIn Ads',
    },
    TikTokAds: {
        name: 'TikTokAds',
        iconPath: '/static/services/tiktok.png',
        fields: [],
        caption: 'TikTok Ads',
    },
    RedditAds: {
        name: 'RedditAds',
        iconPath: '/static/services/reddit.png',
        fields: [],
        caption: 'Reddit Ads',
    },
    BingAds: {
        name: 'BingAds',
        iconPath: '/static/services/bing-ads.svg',
        fields: [],
        caption: 'Bing Ads',
    },
}

const meta: Meta<typeof LemonMenuOverlay> = {
    title: 'Scenes-App/Marketing Analytics/Cell Actions',
    component: LemonMenuOverlay,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': () => {
                    return [200, MARKETING_SOURCE_ICONS]
                },
            },
        }),
    ],
    parameters: {
        docs: {
            description: {
                component: `
Cell actions and row actions for Marketing Analytics tables.

These menus allow users to:
- Map UTM sources to integrations (Google Ads, Facebook Ads, etc.)
- Map UTM campaigns to integration campaigns
- Remove existing custom mappings
- View default mappings (which cannot be modified)

The menus are hierarchical with submenus for mapping options.
                `,
            },
        },
    },
    tags: ['autodocs'],
}
export default meta

// Extract all submenu items from nested menu structure
function extractAllSubmenus(items: LemonMenuItems): { label: string; items: LemonMenuItems }[] {
    const submenus: { label: string; items: LemonMenuItems }[] = []
    for (const item of items) {
        if (item && 'items' in item && item.items) {
            const sectionItems = item.items as LemonMenuItem[]
            for (const sectionItem of sectionItems) {
                if (sectionItem && 'items' in sectionItem && sectionItem.items) {
                    const label = typeof sectionItem.label === 'string' ? sectionItem.label : 'Submenu'
                    submenus.push({ label, items: sectionItem.items as LemonMenuItems })
                }
            }
        }
    }
    return submenus
}

// Wrapper to display menu items with submenus expanded side-by-side
interface MenuDisplayProps {
    items: LemonMenuItems | null
    title?: string
}

function MenuDisplay({ items, title }: MenuDisplayProps): JSX.Element {
    if (!items) {
        return <div className="text-muted p-4">No menu items available for this state</div>
    }

    const submenus = extractAllSubmenus(items)

    return (
        <div className="flex flex-col gap-4">
            {title && <div className="text-sm font-medium">{title}</div>}
            <div className="flex gap-4 items-start flex-wrap">
                <div className="flex flex-col gap-1">
                    <div className="text-xs text-muted">Main Menu</div>
                    <div className="rounded border p-2 bg-surface-primary w-fit min-w-[200px]">
                        <LemonMenuOverlay items={items} />
                    </div>
                </div>
                {submenus.map((submenu, index) => (
                    <div key={index} className="flex gap-2 items-start">
                        <div className="text-muted self-center text-lg">→</div>
                        <div className="flex flex-col gap-1">
                            <div className="text-xs text-muted">{submenu.label}</div>
                            <div className="rounded border p-2 bg-surface-primary w-fit min-w-[200px]">
                                <LemonMenuOverlay items={submenu.items} />
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

export const SourceCellAction_Unmapped: StoryFn = () => {
    const items = buildSourceMappingMenuItems({
        utmSource: 'paid_search',
        mappingStatus: { type: MappingTypes.Unmapped },
        availableIntegrations: [...VALID_NATIVE_MARKETING_SOURCES],
        onOpenIntegrationSettings: () => alert('Opening settings'),
    })

    return <MenuDisplay items={items} title="Source: Unmapped (can be mapped to any integration)" />
}

SourceCellAction_Unmapped.parameters = {
    docs: {
        description: {
            story: 'Source cell action when the UTM source is not mapped to any integration. Shows available integrations to map to.',
        },
    },
}

export const SourceCellAction_CustomMapped: StoryFn = () => {
    const items = buildSourceMappingMenuItems({
        utmSource: 'paid_search',
        mappingStatus: { type: MappingTypes.Custom, integration: 'GoogleAds' },
        availableIntegrations: [],
        onRemoveMapping: () => alert('Removing mapping'),
    })

    return <MenuDisplay items={items} title="Source: Custom Mapped (can be removed)" />
}
SourceCellAction_CustomMapped.parameters = {
    docs: {
        description: {
            story: 'Source cell action when the UTM source has a custom mapping. Shows option to remove the mapping.',
        },
    },
}

export const SourceCellAction_DefaultMapped: StoryFn = () => {
    const items = buildSourceMappingMenuItems({
        utmSource: 'google',
        mappingStatus: { type: MappingTypes.Default, integration: 'GoogleAds' },
        availableIntegrations: [],
    })

    return <MenuDisplay items={items} title="Source: Default Mapped (cannot be modified)" />
}
SourceCellAction_DefaultMapped.parameters = {
    docs: {
        description: {
            story: 'Source cell action when the UTM source matches a default mapping (e.g., "google" → Google Ads). The mapping option is disabled since default mappings cannot be modified.',
        },
    },
}

/** Campaign Cell Actions Stories */
export const CampaignCellAction_Unmapped: StoryFn = () => {
    const items = buildCampaignMappingMenuItems({
        utmCampaign: 'summer_sale_2024',
        globalMapping: null,
        existingMappings: [],
        availableIntegrations: [...VALID_NATIVE_MARKETING_SOURCES],
        onOpenIntegrationSettings: () => alert('Opening settings'),
    })

    return <MenuDisplay items={items} title="Campaign: Unmapped (can be mapped to any integration)" />
}
CampaignCellAction_Unmapped.parameters = {
    docs: {
        description: {
            story: 'Campaign cell action when the UTM campaign is not mapped. Shows available integrations to map to.',
        },
    },
}

export const CampaignCellAction_GloballyMapped: StoryFn = () => {
    const items = buildCampaignMappingMenuItems({
        utmCampaign: 'retargeting_q4',
        globalMapping: { integration: 'MetaAds', campaignName: 'Retargeting Campaign' },
        existingMappings: [],
        availableIntegrations: [],
    })

    return <MenuDisplay items={items} title="Campaign: Globally Mapped (disabled)" />
}
CampaignCellAction_GloballyMapped.parameters = {
    docs: {
        description: {
            story: 'Campaign cell action when the UTM campaign is already mapped globally. The mapping option is disabled.',
        },
    },
}

/** Row Actions Stories */
export const RowActions_Combined: StoryFn = () => {
    const items = buildRowMappingMenuItems({
        sourceValue: 'facebook',
        campaignValue: 'retargeting_q4',
        sourceMappingStatus: { type: MappingTypes.Unmapped },
        availableSourceIntegrations: [...VALID_NATIVE_MARKETING_SOURCES],
        globalCampaignMapping: null,
        existingCampaignMappings: [],
        availableCampaignIntegrations: [...VALID_NATIVE_MARKETING_SOURCES],
        onOpenSourceSettings: () => alert('Opening source settings'),
        onOpenCampaignSettings: () => alert('Opening campaign settings'),
    })

    return <MenuDisplay items={items} title="Row Actions: Both Source and Campaign can be mapped" />
}
RowActions_Combined.parameters = {
    docs: {
        description: {
            story: 'Row actions that combine both source and campaign mapping options. Appears in the row actions menu (three dots) at the end of each row.',
        },
    },
}

export const RowActions_SourceDefaultMapped: StoryFn = () => {
    const items = buildRowMappingMenuItems({
        sourceValue: 'google',
        campaignValue: 'black_friday_sale',
        sourceMappingStatus: { type: MappingTypes.Default, integration: 'GoogleAds' },
        availableSourceIntegrations: [],
        globalCampaignMapping: null,
        existingCampaignMappings: [],
        availableCampaignIntegrations: [...VALID_NATIVE_MARKETING_SOURCES],
        onOpenSourceSettings: () => alert('Opening source settings'),
        onOpenCampaignSettings: () => alert('Opening campaign settings'),
    })

    return (
        <MenuDisplay items={items} title="Row Actions: Source is default mapped (disabled), Campaign can be mapped" />
    )
}
RowActions_SourceDefaultMapped.parameters = {
    docs: {
        description: {
            story: 'Row actions where the source has a default mapping (disabled) but the campaign can still be mapped.',
        },
    },
}
