import type { Meta, StoryObj } from '@storybook/react'

import { DashboardPlacement, DashboardTile, InsightColor, QueryBasedInsightModel } from '~/types'

import { DashboardImageTile } from 'products/dashboards/frontend/components/ImageTile/DashboardImageTile'

const IMAGE_URL = 'https://imagedelivery.net/lvc9lblm6_VvsB0sE7lLrg/70-s-dance-hog/md'

const transparentTile: DashboardTile<QueryBasedInsightModel> = {
    id: 1,
    color: InsightColor.White,
    transparent_background: true,
}

const image = {
    src: IMAGE_URL,
    alt: 'Abstract red and yellow image',
    title: '',
    layout: 'contain' as const,
    position: { x: 50, y: 50 },
}

const meta: Meta<typeof DashboardImageTile> = {
    title: 'Products/Dashboards/Tiles/Dashboard Image Tile',
    component: DashboardImageTile,
    parameters: {
        layout: 'fullscreen',
    },
    argTypes: {
        image: {
            control: 'object',
        },
    },
    args: {
        tile: transparentTile,
        image,
        placement: DashboardPlacement.Dashboard,
        className: 'm-8 h-96 w-full max-w-3xl',
    },
}

export default meta
type Story = StoryObj<typeof DashboardImageTile>

export const Default: Story = {}

export const OpaqueCard: Story = {
    args: {
        tile: {
            ...transparentTile,
            transparent_background: false,
        },
    },
}
