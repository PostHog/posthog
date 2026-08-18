import type { Meta, StoryObj } from '@storybook/react'

import { DashboardTileMovementPreview } from './DashboardTileMovementPreview'

const meta: Meta<typeof DashboardTileMovementPreview> = {
    component: DashboardTileMovementPreview,
    title: 'Products/Dashboards/Dashboard customization/Tile movement',
}

export default meta

type Story = StoryObj<typeof DashboardTileMovementPreview>

export const FillEmptySpaceAbove: Story = {
    args: { mode: 'vertical' },
}

export const MakeRoomInTheRow: Story = {
    args: { mode: 'horizontal' },
}

export const MoveOnlyOverlappingTiles: Story = {
    args: { mode: 'stable' },
}
