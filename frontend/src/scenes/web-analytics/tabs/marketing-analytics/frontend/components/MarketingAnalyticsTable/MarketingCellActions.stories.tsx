import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { IconChevronRight, IconTrash } from '@posthog/icons'

import { LemonMenuItem, LemonMenuItems, LemonMenuOverlay, LemonMenuOverlayProps } from 'lib/lemon-ui/LemonMenu'
import { IconLink } from 'lib/lemon-ui/icons'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

type Story = StoryObj<typeof LemonMenuOverlay>

const meta: Meta<typeof LemonMenuOverlay> = {
    title: 'Scenes-App/Marketing Analytics/Cell Actions',
    component: LemonMenuOverlay,
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

const Template: StoryFn<typeof LemonMenuOverlay> = (props: LemonMenuOverlayProps) => {
    return (
        <div className="rounded border p-1 bg-surface-primary w-fit">
            <LemonMenuOverlay {...props} />
        </div>
    )
}

// Source Cell Actions - Unmapped state
export const SourceCellAction_Unmapped: Story = Template.bind({})
SourceCellAction_Unmapped.args = {
    items: [
        {
            title: '"google"',
            items: [
                {
                    label: 'Mapping',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: [
                        {
                            label: 'Map to Google Ads',
                            icon: <DataWarehouseSourceIcon type="Google Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening Google Ads mapping settings'),
                        },
                        {
                            label: 'Map to Facebook Ads',
                            icon: <DataWarehouseSourceIcon type="Facebook Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening Facebook Ads mapping settings'),
                        },
                        {
                            label: 'Map to LinkedIn Ads',
                            icon: <DataWarehouseSourceIcon type="LinkedIn Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening LinkedIn Ads mapping settings'),
                        },
                    ],
                },
            ],
        },
    ] as LemonMenuItems,
}
SourceCellAction_Unmapped.parameters = {
    docs: {
        description: {
            story: 'Source cell action when the UTM source is not mapped to any integration. Shows available integrations to map to.',
        },
    },
}

// Source Cell Actions - Custom mapped state
export const SourceCellAction_CustomMapped: Story = Template.bind({})
SourceCellAction_CustomMapped.args = {
    items: [
        {
            title: '"paid_search"',
            items: [
                {
                    label: 'Mapping',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: [
                        {
                            label: 'Remove mapping from Google Ads',
                            icon: <IconTrash />,
                            status: 'danger' as const,
                            onClick: () => alert('Removing mapping'),
                        },
                    ],
                },
            ],
        },
    ] as LemonMenuItems,
}
SourceCellAction_CustomMapped.parameters = {
    docs: {
        description: {
            story: 'Source cell action when the UTM source has a custom mapping. Shows option to remove the mapping.',
        },
    },
}

// Source Cell Actions - Default mapped state (disabled)
export const SourceCellAction_DefaultMapped: Story = Template.bind({})
SourceCellAction_DefaultMapped.args = {
    items: [
        {
            title: '"google"',
            items: [
                {
                    label: 'Mapping',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    disabledReason: 'This matches a default mapping, so it cannot be modified.',
                },
            ],
        },
    ] as LemonMenuItems,
}
SourceCellAction_DefaultMapped.parameters = {
    docs: {
        description: {
            story: 'Source cell action when the UTM source matches a default mapping. The mapping option is disabled since default mappings cannot be modified.',
        },
    },
}

// Campaign Cell Actions - Unmapped state
export const CampaignCellAction_Unmapped: Story = Template.bind({})
CampaignCellAction_Unmapped.args = {
    items: [
        {
            title: '"summer_sale_2024"',
            items: [
                {
                    label: 'Mapping',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: [
                        {
                            label: 'Map to Google Ads',
                            icon: <DataWarehouseSourceIcon type="Google Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening Google Ads campaign mapping'),
                        },
                        {
                            label: 'Map to Facebook Ads',
                            icon: <DataWarehouseSourceIcon type="Facebook Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening Facebook Ads campaign mapping'),
                        },
                    ],
                },
            ],
        },
    ] as LemonMenuItems,
}
CampaignCellAction_Unmapped.parameters = {
    docs: {
        description: {
            story: 'Campaign cell action when the UTM campaign is not mapped. Shows available integrations to map to.',
        },
    },
}

// Campaign Cell Actions - With existing mappings
export const CampaignCellAction_WithMappings: Story = Template.bind({})
CampaignCellAction_WithMappings.args = {
    items: [
        {
            title: '"brand_awareness"',
            items: [
                {
                    label: 'Mapping',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: [
                        {
                            label: 'Map to LinkedIn Ads',
                            icon: <DataWarehouseSourceIcon type="LinkedIn Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening LinkedIn Ads campaign mapping'),
                        },
                        {
                            label: 'Remove from Google Ads: Brand Campaign Q4',
                            icon: <IconTrash />,
                            status: 'danger' as const,
                            onClick: () => alert('Removing Google Ads mapping'),
                        },
                        {
                            label: 'Remove from Facebook Ads: Brand Awareness 2024',
                            icon: <IconTrash />,
                            status: 'danger' as const,
                            onClick: () => alert('Removing Facebook Ads mapping'),
                        },
                    ],
                },
            ],
        },
    ] as LemonMenuItems,
}
CampaignCellAction_WithMappings.parameters = {
    docs: {
        description: {
            story: 'Campaign cell action with existing mappings. Shows both available integrations to map to and existing mappings that can be removed.',
        },
    },
}

// Row Actions - Combined source and campaign
export const RowActions_Combined: Story = Template.bind({})
RowActions_Combined.args = {
    items: [
        {
            title: 'Mapping',
            items: [
                {
                    label: 'Source: "facebook"',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: [
                        {
                            label: 'Map to Facebook Ads',
                            icon: <DataWarehouseSourceIcon type="Facebook Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening Facebook Ads source mapping'),
                        },
                        {
                            label: 'Map to Meta Ads',
                            icon: <DataWarehouseSourceIcon type="Meta Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening Meta Ads source mapping'),
                        },
                    ],
                },
                {
                    label: 'Campaign: "retargeting..."',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: [
                        {
                            label: 'Map to Facebook Ads',
                            icon: <DataWarehouseSourceIcon type="Facebook Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening Facebook Ads campaign mapping'),
                        },
                        {
                            label: 'Remove from Google Ads: Retargeting Q4',
                            icon: <IconTrash />,
                            status: 'danger' as const,
                            onClick: () => alert('Removing Google Ads mapping'),
                        },
                    ],
                },
            ] as LemonMenuItem[],
        },
    ] as LemonMenuItems,
}
RowActions_Combined.parameters = {
    docs: {
        description: {
            story: 'Row actions that combine both source and campaign mapping options. Appears in the row actions menu (three dots) at the end of each row.',
        },
    },
}

// Row Actions - Source with default mapping (disabled)
export const RowActions_SourceDefaultMapped: Story = Template.bind({})
RowActions_SourceDefaultMapped.args = {
    items: [
        {
            title: 'Mapping',
            items: [
                {
                    label: 'Source: "google"',
                    icon: <IconLink />,
                    disabledReason: 'This matches a default mapping, so it cannot be modified.',
                },
                {
                    label: 'Campaign: "black_friday"',
                    icon: <IconLink />,
                    sideIcon: <IconChevronRight />,
                    items: [
                        {
                            label: 'Map to Google Ads',
                            icon: <DataWarehouseSourceIcon type="Google Ads" size="xsmall" disableTooltip />,
                            onClick: () => alert('Opening Google Ads campaign mapping'),
                        },
                    ],
                },
            ] as LemonMenuItem[],
        },
    ] as LemonMenuItems,
}
RowActions_SourceDefaultMapped.parameters = {
    docs: {
        description: {
            story: 'Row actions where the source has a default mapping (disabled) but the campaign can still be mapped.',
        },
    },
}
