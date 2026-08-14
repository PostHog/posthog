import type { Meta, StoryObj } from '@storybook/react'

import { DashboardSection } from './DashboardSection'

const group = {
    id: 'section-1',
    name: 'Acquisition',
    position: 0,
    member_tile_ids: [1],
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2026-01-01T00:00:00Z',
    last_modified_by: null,
}

const gridProps = {
    children: null,
    width: 640,
    rowHeight: 80,
    margin: [16, 16] as [number, number],
    containerPadding: [0, 0] as [number, number],
    layouts: {
        sm: [{ i: '1', x: 0, y: 0, w: 6, h: 2 }],
    },
    cols: { sm: 12, xs: 1 },
    breakpoints: { sm: 768, xs: 0 },
}

const meta: Meta<typeof DashboardSection> = {
    title: 'Scenes/Dashboard/Dashboard Section',
    component: DashboardSection,
    args: {
        group,
        collapsed: false,
        canEdit: true,
        tileCount: 1,
        overlay: null,
        gridBackgroundProps: null,
        gridProps,
        onToggle: () => {},
        onRename: () => {},
        onDelete: () => {},
        children: (
            <div key="1" className="bg-surface-primary border border-primary rounded p-2">
                Sample tile
            </div>
        ),
    },
}
export default meta

type Story = StoryObj<typeof DashboardSection>

export const Named: Story = {}

export const Anonymous: Story = {
    args: { group: null },
}

export const Collapsed: Story = {
    args: { collapsed: true },
}

export const Empty: Story = {
    args: {
        tileCount: 0,
        children: null,
        gridProps: { ...gridProps, layouts: { sm: [] } },
    },
}

export const Highlighted: Story = {
    args: { highlighted: true },
}
