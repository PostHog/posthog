import type { Meta, StoryObj } from '@storybook/react'

import { DashboardPlacement, DashboardTile, InsightColor, QueryBasedInsightModel } from '~/types'

import { DashboardSeparatorTile } from 'products/dashboards/frontend/components/SeparatorTile/DashboardSeparatorTile'

const tile: DashboardTile<QueryBasedInsightModel> = {
    id: 1,
    color: InsightColor.White,
    transparent_background: true,
}

const meta: Meta<typeof DashboardSeparatorTile> = {
    title: 'Products/Dashboards/Tiles/Dashboard Separator Tile',
    component: DashboardSeparatorTile,
    parameters: {
        layout: 'fullscreen',
    },
    args: {
        tile,
        thickness: 'thin',
        placement: DashboardPlacement.Dashboard,
        className: 'm-8 h-20 w-full max-w-3xl',
    },
}

export default meta
type Story = StoryObj<typeof DashboardSeparatorTile>

export const Default: Story = {}

export const Thick: Story = {
    args: {
        thickness: 'thick',
    },
}
