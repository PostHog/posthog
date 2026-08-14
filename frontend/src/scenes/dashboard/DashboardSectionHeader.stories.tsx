import type { Meta, StoryObj } from '@storybook/react'

import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { DashboardSectionHeader } from './DashboardSectionHeader'

const group = (overrides: Partial<DashboardGroupApi> = {}): DashboardGroupApi => ({
    id: 'section-1',
    name: 'Acquisition',
    position: 1,
    member_tile_ids: [1, 2],
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2026-01-01T00:00:00Z',
    last_modified_by: null,
    ...overrides,
})

const meta: Meta<typeof DashboardSectionHeader> = {
    title: 'Scenes/Dashboard/Dashboard Section Header',
    component: DashboardSectionHeader,
    args: {
        group: group(),
        collapsed: false,
        canEdit: true,
        tileCount: 2,
        onToggle: () => {},
        onRename: () => {},
        onDelete: () => {},
    },
}
export default meta

type Story = StoryObj<typeof DashboardSectionHeader>

export const Default: Story = {}

export const Draggable: Story = {
    args: {},
}

export const Collapsed: Story = {
    args: { collapsed: true },
}

export const ReadOnly: Story = {
    args: { canEdit: false },
}

export const Untitled: Story = {
    args: { group: group({ name: null }) },
}

export const FirstSection: Story = {
    args: { group: group({ position: 0 }) },
}
